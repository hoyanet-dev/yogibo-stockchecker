#!/usr/bin/env python3
"""요기보 허기보 프리미엄 플러스 재고 확인 → 재고 있으면 카카오톡 '나에게 보내기'.

한 번 실행하고 끝나는 스크립트 (GitHub Actions cron이 주기적으로 실행).
표준 라이브러리만 사용. 설정은 환경변수:
  KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN   (필수, 알림 보낼 때)
  KAKAO_CLIENT_SECRET                       (카카오에서 Client Secret을 켰다면)
  GH_PAT                                    (선택: 갱신된 refresh token을 GitHub Secret에 자동 저장)

  python3 stockchecker.py --once   # 현재 재고만 출력 (알림 안 보냄)
  python3 stockchecker.py          # 재고 있으면 카톡 전송
  python3 stockchecker.py --test-kakao  # 테스트 카톡 1회 전송
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

URL = ("https://yogibo.kr/product/%ED%97%88%EA%B8%B0%EB%B3%B4-%ED%94%84%EB%A6%AC%EB%AF%B8"
       "%EC%97%84-%ED%94%8C%EB%9F%AC%EC%8A%A4/1323/category/534/display/1/")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def fetch_stock():
    """{색상: 재고수량} 반환. 파싱 실패 시 예외."""
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    m = re.search(r"var option_stock_data = '(.*?)';\s*var ", html, re.S) or \
        re.search(r"var option_stock_data = '(.*?)';", html, re.S)
    if not m:
        raise RuntimeError("option_stock_data를 찾지 못함 (페이지 구조가 바뀐 듯)")
    raw = re.sub(r'\\(["\\/])', r"\1", m.group(1))  # JS 문자열 이스케이프 한 겹 제거
    data = json.loads(raw)
    return {v["option_value"].split("/")[-1].strip(): int(v["stock_number"]) for v in data.values()}


def post(url, fields, headers=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), headers=headers or {})
    return json.load(urllib.request.urlopen(req, timeout=20))


def refresh_access_token():
    fields = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_API_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        fields["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    tok = post("https://kauth.kakao.com/oauth/token", fields)
    # 만료가 1달 이내로 남으면 카카오가 새 refresh token을 내려준다 → 저장 안 하면 60일 뒤 끊김
    new_rt = tok.get("refresh_token")
    if new_rt and new_rt != os.environ["KAKAO_REFRESH_TOKEN"]:
        save_new_refresh_token(new_rt)
    return tok["access_token"]


def save_new_refresh_token(new_rt):
    repo, pat = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_PAT")
    if not (repo and pat):
        print("::warning::새 refresh token이 발급됐지만 GH_PAT이 없어 저장하지 못했습니다. "
              "kakao_auth.py로 토큰을 다시 발급해 KAKAO_REFRESH_TOKEN 시크릿을 갱신하세요.")
        return
    subprocess.run(["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--repo", repo],
                   input=new_rt.encode(), env={**os.environ, "GH_TOKEN": pat}, check=True)
    print("refresh token을 GitHub Secret에 갱신했습니다.")


def send_kakao(text):
    access = refresh_access_token()
    # 링크 도메인이 카카오 앱에 등록돼 있지 않으면 버튼 링크가 localhost로 가므로 본문에도 URL을 직접 넣는다
    text = f"{text}\n{URL}"
    assert len(text) <= 200, f"카카오 text 한도(200자) 초과: {len(text)}"
    template = {"object_type": "text", "text": text,
                "link": {"web_url": URL, "mobile_web_url": URL}, "button_title": "상품 페이지 열기"}
    res = post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
               {"template_object": json.dumps(template, ensure_ascii=False)},
               {"Authorization": f"Bearer {access}"})
    if res.get("result_code") != 0:
        raise RuntimeError(f"카톡 전송 실패: {res}")
    print("카카오톡 전송 완료")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="재고만 출력, 알림 안 보냄")
    ap.add_argument("--test-kakao", action="store_true", help="재고와 상관없이 테스트 카톡 1회 전송")
    args = ap.parse_args()

    if args.test_kakao:
        send_kakao("✅ 재고 알림 테스트입니다.")
        return 0

    stock = fetch_stock()
    print(stock)
    avail = {c: n for c, n in stock.items() if n > 0}
    if args.once or not avail:
        return 0
    send_kakao("🎉 허기보 재고 떴어요! " + ", ".join(avail))
    # 알림을 보냈다는 표시 → 워크플로가 다음 단계에서 스스로 비활성화한다
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("notified=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
