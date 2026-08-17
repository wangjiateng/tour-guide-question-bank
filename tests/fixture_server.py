"""Local fixture HTTP server emulating tour-guide question sources.

Serves:
- `/`            an HTML question page (validates static_page adapter)
- `/api/questions`  a paged JSON question API (validates json_api adapter)
so both adapter kinds can be validated end-to-end without external network.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

PAGE = """<!DOCTYPE html>
<html><head><title>全国导游资格考试模拟试题 - 导游考试题库</title></head>
<body>
<h1>2024年全国导游资格考试模拟试题</h1>
<p>1. 导游人员在带团过程中，遇有突发疾病游客，下列做法正确的是（ ）。</p>
<p>A. 置之不理 B. 立即联系医疗机构并协助救助 C. 让游客自行处理 D. 继续行程</p>
<p>参考答案：B</p>
<p>2. 中国旅游日的日期是（ ）。</p>
<p>A. 5月1日 B. 5月19日 C. 6月1日 D. 10月1日</p>
<p>答案：B</p>
<p>3. 导游证的有效期为（ ）年。</p>
<p>A. 1 B. 2 C. 3 D. 5</p>
<p>参考答案：C</p>
</body></html>
"""

JSON_PAGE_SIZE = 3
JSON_QUESTIONS = [
    {"question": f"导游服务规范第{i}题：下列属于导游职责的是（ ）。",
     "options": {"A": "制定旅游合同", "B": "提供导游讲解服务", "C": "管理景区门票", "D": "安排游客住宿"},
     "answer": "B",
     "explanation": f"导游核心职责是提供导游讲解服务（题{i}）。"}
    for i in range(1, 8)
]

# Variant platform: same questions as the HTML page but with full-width
# punctuation, leading question numbers, and inline whitespace — the
# cross-platform dedupe (normalized_text) must collapse these onto the
# exact-text rows instead of inserting duplicates.
VARIANT_QUESTIONS = [
    {"question": "1. 导游人员在带团过程中,遇有突发疾病游客,下列做法正确的是( )。",
     "options": {"A": "置之不理", "B": "立即联系医疗机构并协助救助",
                 "C": "让游客自行处理", "D": "继续行程"},
     "answer": "B"},
    {"question": "2. 中国旅游日的日期是( )。",
     "options": {"A": "5月1日", "B": "5月19日", "C": "6月1日", "D": "10月1日"},
     "answer": "B"},
    {"question": "3. 导游证的有效期为( )年。",
     "options": {"A": "1", "B": "2", "C": "3", "D": "5"},
     "answer": "C"},
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/variant"):
            self._serve_variant()
        elif self.path.startswith("/api/questions"):
            self._serve_json()
        else:
            self._serve_html()

    def _serve_variant(self):
        import json

        body = json.dumps(
            {"data": VARIANT_QUESTIONS, "has_more": False},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self):
        import json
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        page = int(qs.get("page", ["1"])[0])
        start = (page - 1) * JSON_PAGE_SIZE
        chunk = JSON_QUESTIONS[start:start + JSON_PAGE_SIZE]
        body = json.dumps(
            {"data": chunk, "has_more": start + JSON_PAGE_SIZE < len(JSON_QUESTIONS)},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def serve(port: int = 18923):
    server = HTTPServer(("127.0.0.1", port), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    serve()
    print("fixture server on 127.0.0.1:18923")
    import time
    time.sleep(3600)
