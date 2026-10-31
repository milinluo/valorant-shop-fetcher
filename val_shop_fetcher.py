# -*- coding: utf-8 -*-
"""无畏契约每日商店自动获取器（本地版）
纯标准库实现，零第三方依赖。流程：
1. QQ 扫码登录（掌上无畏契约授权链路）→ 保存 userId/tid 凭证
2. 本地 HTTP 服务 (localhost:4175) 提供 /api/shop，供网页"自动获取今日商店"按钮调用
用法：
  双击启动脚本，或命令行运行：python val_shop_fetcher.py
  首次运行会自动弹二维码，用手机 QQ 扫码后凭证自动保存到 auth.json
"""
import base64
import http.server
import io
import json
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

PORT = 4175
AUTH_FILE = Path(__file__).resolve().parent / "auth.json"
QR_FILE = Path(__file__).resolve().parent / "qr_login.png"

LOGIN_URL_TEMPLATE = (
    "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?pt_enable_pwd=1&appid=716027609"
    "&pt_3rd_aid=102061775&daid=381&pt_skey_valid=0&style=35&force_qr=1&autorefresh=1"
    "&s_url=http%3A%2F%2Fconnect.qq.com&refer_cgi=m_authorize&ucheck=1&fall_to_wv=1"
    "&status_os=12&redirect_uri=auth%3A%2F%2Ftauth.qq.com%2F&client_id=102061775"
    "&pf=openmobile_android&response_type=token&scope=all&sdkp=a&sdkv=3.5.17.lite"
    "&sign=a6479455d3e49b597350f13f776a6288&status_machine=MjMxMTdSSzY2Qw%3D%3D"
    "&switch=1&time=1763280194&show_download_ui=true&h5sig=trobryxo8IPM0GaSQH12mowKG"
    "-CY65brFzkK7_-9EW4&loginty=6"
)
PTQR_SHOW_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
PTQR_LOGIN_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin"
OPENMOBILE_REDIRECT_URL = "https://openmobile.qq.com/oauth2.0/m_get_redirect_url"
LOGIN_BY_QQ_URL = "https://app.mval.qq.com/go/auth/login_by_qq?source_game_zone=agame&game_zone=agame"
STORE_API_URL = "https://app.mval.qq.com/go/mlol_store/agame/user_store"
PTQR_AID = "716027609"
PTQR_DAID = "381"
PTQR_THIRD_AID = "102061775"

UA_GAME = (
    "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36 tencent_game_emulator"
)
UA_MVAL = (
    "mval/2.4.0.10053 Channel/10068 Manufacturer/Redmi  Mozilla/5.0 (Linux; Android 12; "
    "23117RK66C Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)


# ---------- 通用 HTTP 工具 ----------
class Http:
    def __init__(self):
        self.cookies = {}

    def set_cookies(self, url: str, headers=None):
        """把已有 cookie 填进 headers。"""
        if not self.cookies:
            return
        pairs = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        headers = headers or {}
        headers["Cookie"] = pairs

    def update_cookies(self, resp_headers):
        for name, value in resp_headers.items():
            if name.lower() == "set-cookie":
                cookie = SimpleCookie(value)
                for key, morsel in cookie.items():
                    self.cookies[key] = morsel.value

    def request(self, url, params=None, headers=None, data=None, timeout=20):
        full = url
        if params:
            full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        headers = dict(headers or {})
        headers.setdefault("User-Agent", UA_GAME)
        self.set_cookies(full, headers)
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(full, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                self.update_cookies(resp.headers)
                raw = resp.read()
                return resp.status, raw
        except urllib.error.HTTPError as e:
            self.update_cookies(e.headers)
            return e.code, e.read()


# ---------- QQ 扫码登录 ----------
def _calc_ptqrtoken(qrsig: str) -> int:
    token = 0
    for ch in qrsig:
        token += (token << 5) + ord(ch)
    return token & 2147483647


def _parse_ptui_callback(text: str):
    m = re.search(r"ptuiCB\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'", text)
    if not m:
        return None
    return {
        "code": m.group(1),
        "redirect_url": m.group(3).replace("\\/", "/").replace("\\x26", "&"),
        "message": m.group(5),
    }


def _extract_login_data(success_url: str) -> dict:
    """从回调 URL 里提取 openid/access_token 等参数（含嵌套跳转）。"""
    merged = {}

    def normalize_url(u):
        return (u or "").replace("\\/", "/").replace("\\x26", "&").strip()

    def parse_part(raw):
        part = raw.replace("#&", "&").lstrip("&")
        for k, v in urllib.parse.parse_qs(part, keep_blank_values=True).items():
            if v and k not in merged:
                merged[k] = v[0]

    nested_keys = {"u1", "url", "jump_url", "redirect_uri", "redirect_url", "target_url",
                   "s_url", "f_url", "qtarget", "jump", "ru"}
    queue = [normalize_url(success_url)]
    visited = set()
    while queue:
        candidate = queue.pop(0)
        if not candidate or candidate in visited:
            continue
        visited.add(candidate)
        decoded = candidate
        for _ in range(3):
            nxt = urllib.parse.unquote(decoded)
            if nxt == decoded:
                break
            decoded = nxt
        parsed = urllib.parse.urlparse(decoded)
        for raw in (parsed.query, parsed.fragment):
            parse_part(raw)
        if not merged and ("openid=" in decoded or "access_token=" in decoded):
            parse_part(decoded)
        for nk in nested_keys:
            nv = merged.get(nk, "")
            if nv and nv not in visited:
                queue.append(normalize_url(nv))
    return {
        "openid": merged.get("openid", ""),
        "appid": merged.get("appid", ""),
        "access_token": merged.get("access_token", ""),
        "pay_token": merged.get("pay_token", ""),
        "key": merged.get("key", ""),
        "redirect_uri_key": merged.get("redirect_uri_key", ""),
    }


def _extract_auth_url(text: str) -> str:
    m = re.search(r"(auth://tauth\.qq\.com/[^\s\"'<>]+)", text or "")
    if m:
        return m.group(1)
    m2 = re.search(r"_Callback\s*\(\s*(\{.*?\})\s*\)\s*;?", text or "", re.DOTALL)
    if m2:
        try:
            payload = json.loads(m2.group(1))
            u = str(payload.get("url", "") or "")
            if u.startswith("auth://"):
                return u
        except Exception:
            pass
    return ""


def _build_pt_openlogin_data(query_map: dict) -> str:
    tid = str(int(time.time()))
    auth_time = str(int(time.time() * 1000))
    items = [
        ("which", ""), ("refer_cgi", query_map.get("refer_cgi", ["m_authorize"])[0]),
        ("response_type", query_map.get("response_type", ["token"])[0]),
        ("client_id", query_map.get("client_id", [PTQR_THIRD_AID])[0]),
        ("state", ""), ("display", ""), ("openapi", "1011"),
        ("switch", query_map.get("switch", ["1"])[0]), ("src", "1"),
        ("sdkv", query_map.get("sdkv", ["3.5.17.lite"])[0]), ("sdkp", query_map.get("sdkp", ["a"])[0]),
        ("tid", tid), ("pf", query_map.get("pf", ["openmobile_android"])[0]),
        ("need_pay", "0"), ("browser", "0"), ("browser_error", ""), ("serial", ""),
        ("token_key", ""), ("redirect_uri", query_map.get("redirect_uri", ["auth://tauth.qq.com/"])[0]),
        ("sign", query_map.get("sign", [""])[0]), ("time", query_map.get("time", [""])[0]),
        ("status_version", ""), ("status_os", query_map.get("status_os", ["12"])[0]),
        ("status_machine", query_map.get("status_machine", [""])[0]), ("page_type", "1"),
        ("has_auth", "1"), ("update_auth", "1"), ("auth_time", auth_time),
        ("loginfrom", ""), ("h5sig", query_map.get("h5sig", [""])[0]),
        ("loginty", query_map.get("loginty", ["6"])[0]),
    ]
    return urllib.parse.urlencode(items)


def qq_login(timeout_sec: int = 60):
    """QQ 扫码登录。返回 (userId, tid)；失败抛异常。二维码写入 qr_login.png 并自动打开。"""
    http = Http()
    login_url = LOGIN_URL_TEMPLATE
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://openmobile.qq.com/",
        "X-Requested-With": "com.tencent.apps.valorant",
    }
    # 1. 访问 xlogin 初始化会话
    status, body = http.request(login_url, headers=headers)
    page = body.decode("utf-8", errors="ignore")
    login_sig = ""
    m = re.search(r"g_login_sig=encodeURIComponent\(\"([^\"]+)\"\)", page)
    if m:
        login_sig = m.group(1)
    login_sig = login_sig or http.cookies.get("pt_login_sig", "")

    parsed = urllib.parse.urlparse(login_url)
    query_map = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    u1 = query_map.get("s_url", ["http://connect.qq.com"])[0]
    pt_uistyle = query_map.get("style", ["35"])[0]
    ptlang = query_map.get("ptlang", ["2052"])[0]
    jsver = "28d22679"
    m2 = re.search(r"/monorepo/([0-9A-Za-z]+)/ptlogin/js/", page)
    if m2:
        jsver = m2.group(1)
    pt_openlogin_data = _build_pt_openlogin_data(query_map)

    # 2. 获取二维码
    qr_params = {
        "s": "8", "e": "0", "appid": PTQR_AID, "type": "0",
        "t": str(random.random()), "u1": u1, "daid": PTQR_DAID,
        "pt_3rd_aid": PTQR_THIRD_AID,
    }
    qr_headers = {"Referer": login_url, "Accept": "image/*,*/*;q=0.8",
                  "X-Requested-With": "com.tencent.apps.valorant"}
    status, qr_bytes = http.request(PTQR_SHOW_URL, params=qr_params, headers=qr_headers)
    if not qr_bytes:
        raise RuntimeError("二维码获取失败")
    qrsig = http.cookies.get("qrsig", "")
    if not qrsig:
        raise RuntimeError("未获取到 qrsig")
    QR_FILE.write_bytes(qr_bytes)
    ptqrtoken = _calc_ptqrtoken(qrsig)
    print("二维码已保存到:", QR_FILE)
    # 自动打开二维码图片（Windows 默认看图器）
    try:
        os.startfile(str(QR_FILE))
    except Exception:
        pass
    print("请在 120 秒内用手机 QQ 扫描弹出的二维码（需使用绑定无畏契约的 QQ）…")

    # 3. 轮询登录状态
    poll_headers = {"Referer": login_url, "Accept": "*/*",
                    "X-Requested-With": "com.tencent.apps.valorant"}
    start = time.time()
    while time.time() - start < timeout_sec:
        params = {
            "u1": u1, "from_ui": "1", "type": "1", "ptlang": ptlang,
            "ptqrtoken": str(ptqrtoken), "daid": PTQR_DAID, "aid": PTQR_AID,
            "pt_3rd_aid": PTQR_THIRD_AID, "pt_openlogin_data": pt_openlogin_data,
            "device": "2", "ptopt": "1", "pt_uistyle": pt_uistyle,
            "jsver": jsver, "r": str(random.random()),
        }
        if login_sig:
            params["login_sig"] = login_sig
        status, body = http.request(PTQR_LOGIN_URL, params=params, headers=poll_headers)
        cb = _parse_ptui_callback(body.decode("utf-8", errors="ignore"))
        if not cb:
            time.sleep(2)
            continue
        code = cb["code"]
        if code == "0":
            print("扫码成功，正在换取凭证…")
            login_data = _extract_login_data(cb["redirect_url"])
            if not (login_data.get("openid") and login_data.get("access_token")):
                # 尝试通过 keystr 补全
                for key in ("redirect_uri_key", "keystr", "key"):
                    keystr = login_data.get(key, "")
                    if not keystr:
                        continue
                    try:
                        s2, b2 = http.request(OPENMOBILE_REDIRECT_URL, params={"keystr": keystr},
                                              headers={"Referer": "https://imgcache.qq.com/"})
                        auth_url = _extract_auth_url(b2.decode("utf-8", errors="ignore"))
                        if auth_url:
                            extra = _extract_login_data(auth_url)
                            for k in ("openid", "access_token", "appid", "pay_token"):
                                if not login_data.get(k) and extra.get(k):
                                    login_data[k] = extra[k]
                    except Exception:
                        pass
            if login_data.get("openid") and login_data.get("access_token"):
                return _exchange_token(http, login_data)
            raise RuntimeError("登录成功但未取得 openid/access_token")
        if code == "65":
            raise RuntimeError("二维码已失效，请重新运行登录")
        if code in ("66", "67"):
            time.sleep(2)
            continue
        time.sleep(2)
    raise RuntimeError("扫码超时，请重新运行登录")


def _exchange_token(http: Http, login_data: dict):
    """用 openid/access_token 换取 userId/tid。"""
    headers = {
        "Cookie": "clientType=9; openid=null; access_token=null;",
        "User-Agent": UA_MVAL,
        "Host": "app.mval.qq.com",
        "Connection": "Keep-Alive",
    }
    data = {
        "clienttype": 9,
        "config_params": {"client_dev_name": "23117RK66C", "lang_type": 0},
        "login_info": {
            "appid": int(login_data.get("appid") or 102061775),
            "openid": login_data["openid"],
            "qq_info_type": 5,
            "sig": login_data["access_token"],
            "uin": 0,
        },
        "mappid": 10200,
        "mcode": "132f0a77d34402abc8463d60100011d19b0e",
        "source_game_zone": "agame",
        "game_zone": "agame",
    }
    status, body = http.request(LOGIN_BY_QQ_URL, headers=headers, data=data)
    result = json.loads(body.decode("utf-8", errors="ignore"))
    if result.get("result") != 0:
        raise RuntimeError("换取凭证失败: " + (result.get("msg") or str(result)))
    info = result.get("data", {}).get("login_info", {})
    user_id = str(info.get("user_id", ""))
    tid = str(info.get("wt", ""))
    if not user_id or not tid:
        raise RuntimeError("凭证为空")
    return {"userId": user_id, "tid": tid, "openid": login_data.get("openid", "")}


# ---------- 商店查询 ----------
def fetch_today_shop(auth: dict):
    """获取今日商店，返回皮肤名列表。"""
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json",
        "User-Agent": UA_MVAL,
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Cookie": (
            "clientType=9; uin=o0; appid=102061775; acctype=qc; openid=null; "
            f"access_token=null; userId={auth['userId']}; accountType=5; tid={auth['tid']};"
        ),
    }
    data = {"_t": int(time.time())}
    status, body = http_request_raw(STORE_API_URL, headers=headers, data=data)
    result = json.loads(body.decode("utf-8", errors="ignore"))
    code = result.get("result")
    if code != 0:
        msg = result.get("errMsg") or result.get("msg") or "未知错误"
        if code in (1001, 1003, 999999) or "expire" in str(msg).lower():
            raise PermissionError("登录凭证已失效，请重新扫码登录")
        raise RuntimeError(msg)
    goods = result.get("data")
    if isinstance(goods, list):
        goods = goods[0] if goods else {}
    items = goods.get("list", []) if isinstance(goods, dict) else []
    names = []
    for it in items:
        name = it.get("goods_name")
        if name:
            names.append(str(name))
    return names


def http_request_raw(url, headers=None, data=None, timeout=15):
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---------- 本地 HTTP 服务 ----------
class Handler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            auth = load_auth()
            self._send_json({"auth": auth is not None})
        elif path == "/api/shop":
            auth = load_auth()
            if not auth:
                self._send_json({"auth": False, "error": "未登录，请重启自动获取器扫码登录"}, 200)
                return
            try:
                names = fetch_today_shop(auth)
                today = time.strftime("%Y-%m-%d")
                self._send_json({"auth": True, "date": today, "skins": [{"name": n} for n in names]})
            except PermissionError as e:
                self._send_json({"auth": False, "error": str(e)}, 200)
            except Exception as e:
                self._send_json({"auth": True, "error": f"获取失败：{e}"}, 200)
        elif path == "/api/login":
            self._send_json({"ok": True, "msg": "登录请重启程序并扫码"}, 200)
        else:
            self._send_json({"ok": False}, 404)

    def log_message(self, *args):
        pass


def load_auth():
    if AUTH_FILE.exists():
        try:
            data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            if data.get("userId") and data.get("tid"):
                return data
        except Exception:
            pass
    return None


def main():
    print("无畏契约每日商店自动获取器")
    print("=" * 40)
    auth = load_auth()
    if auth:
        print("已检测到登录凭证（userId=%s…）" % str(auth["userId"])[:6])
        print("如需重新扫码登录，请删除 auth.json 后重启本程序。")
    else:
        print("首次使用，即将弹出 QQ 扫码登录窗口…")
        try:
            auth = qq_login(timeout_sec=120)
            AUTH_FILE.write_text(json.dumps(auth, ensure_ascii=False, indent=2), encoding="utf-8")
            print("登录成功！凭证已保存。")
        except Exception as e:
            print("登录失败：%s" % e)
            print("按回车键退出…")
            input()
            return
    # 启动本地服务
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("端口 %d 被占用（可能已启动）：%s" % (PORT, e))
        input()
        return
    print("本地服务已启动：http://localhost:%d" % PORT)
    print("现在打开网页，点击「自动获取今日商店」即可记录今日 4 个皮肤。")
    print("关闭本窗口即停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
