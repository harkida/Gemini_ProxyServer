import http.server
import socketserver
import requests
import json
import os
from dotenv import load_dotenv

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

# 환경 변수에서 API 키를 가져옵니다.
# .env 파일에 GEMINI_API_KEY="여러분의실제API키" 형식으로 저장되어 있어야 합니다.
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("API 키가 설정되지 않았습니다. .env 파일에 GEMINI_API_KEY를 추가하세요.")

# Gemini API 엔드포인트 URL
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

# LLM에게 보낼 프롬프트의 '틀'입니다.
# {QuestionSentence}와 {StudentAnswer} 부분은 언리얼 엔진에서 받은 내용으로 채워집니다.
PROMPT_TEMPLATE = """
# [역할 및 지시문]
당신은 이탈리아 학생들의 한국어 문장 번역을 평가하는, 정확하고 공정한 AI 채점 보조원입니다. 당신의 임무는 학생이 제출한 이탈리아어 번역문이 원문인 한국어 문장의 의미를 얼마나 정확하게 전달하는지 평가하고, 반드시 정해진 형식에 따라 점수와 통과 여부(True/False)를 출력하는 것입니다.

# [채점 기준 (10점 만점)]
아래 기준에 따라 종합적으로 평가하여 소수점 첫째 자리까지 점수를 매겨주세요.

1.  **의미의 정확성 (최대 5점):**
    *   원문(한국어)의 핵심 의미가 왜곡 없이 완전히 전달되었는가?
    *   (만점 조건) 주어, 목적어, 서술어, 주요 수식어 등 문장의 핵심 요소가 모두 포함되고 정확하게 번역됨.
    *   (감점 요인) 일부 의미 누락, 오역, 불필요한 의미 추가.

2.  **문법 및 구문 (최대 3점):**
    *   학생이 작성한 이탈리아어 문장이 문법적으로 자연스럽고 정확한가?
    *   (만점 조건) 관사, 전치사, 동사 시제 및 활용, 성별/수 일치 등 이탈리아어 문법 규칙을 올바르게 사용함.
    *   (감점 요인) 사소한 문법 오류, 어색한 문장 구조.

3.  **어휘 및 뉘앙스 (최대 2점):**
    *   단어 선택이 적절하고, 원문의 뉘앙스(예: 강조, 추측, 감정)를 잘 살렸는가?
    *   (만점 조건) '정말', '좀', '아마도' 등과 같은 부사나 표현의 미묘한 차이를 적절한 이탈리아어 어휘로 잘 표현함.
    *   (감점 요인) 단어 선택이 부정확하거나 어색함, 원문의 뉘앙스를 전혀 살리지 못함.

# [수행 과정]
1.  아래 `[채점할 내용]`에 주어진 '원문'과 '학생 답안'을 주의 깊게 분석합니다.
2.  위의 '채점 기준'에 따라 '의미의 정확성', '문법 및 구문', '어휘 및 뉘앙스' 각 항목별로 점수를 매깁니다.
3.  각 항목의 점수를 모두 합산하여 최종 점수(10점 만점)를 계산합니다.
4.  산출된 최종 점수가 **7.0점 이상이면 'True'**, 7.0점 미만이면 'False'를 판별합니다.
5.  아래 '출력 형식'에 맞춰 결과를 정확히 두 줄로 출력합니다.

# [출력 형식]
**어떠한 추가 설명이나 문장도 없이, 다음 형식을 반드시 준수하여 출력하세요.**

당신이 쓴 정답의 점수는 ??.?점입니다.
True / False


# [채점할 내용]
*   **원문 (한국어):** {QuestionSentence}
*   **학생 답안 (이탈리아어):** {StudentAnswer}
"""

# 'POST' 요청을 처리하기 위한 새로운 클래스를 정의합니다.
# 이것이 501 에러를 해결하는 핵심입니다.
class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        try:
            # 1. 언리얼 엔진에서 보낸 요청의 본문(body)을 읽습니다.
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # 2. 받은 데이터를 JSON으로 해석합니다.
            client_data = json.loads(post_data)
            question_sentence = client_data.get('question')
            student_answer = client_data.get('answer')

            if not question_sentence or not student_answer:
                raise ValueError("요청에 'question' 또는 'answer' 필드가 없습니다.")

            # 3. 프롬프트 '틀'에 실제 내용(원문, 학생 답안)을 채워 넣어 최종 프롬프트를 완성합니다.
            final_prompt = PROMPT_TEMPLATE.format(QuestionSentence=question_sentence, StudentAnswer=student_answer)
            
            # 4. Gemini API가 요구하는 형식에 맞춰 최종 요청 데이터를 만듭니다.
            gemini_payload = {
                "contents": [{
                    "parts": [{
                        "text": final_prompt
                    }]
                }]
            }

            # 5. 완성된 요청을 실제 Gemini API로 전송합니다.
            headers = {'Content-Type': 'application/json'}
            response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(gemini_payload))
            response.raise_for_status() # 오류가 있으면 예외를 발생시킵니다.

            # 6. Gemini API의 응답을 처리합니다.
            response_json = response.json()
            result_text = response_json['candidates'][0]['content']['parts'][0]['text']

            parts = result_text.strip().split('\n')
            display_message = parts[0] if len(parts) > 0 else "메시지를 받지 못했습니다."
            is_correct_str = parts[1] if len(parts) > 1 else "False"

            response_data = {
                "message": display_message,
                "isCorrect": is_correct_str.lower() == 'true' # "True" 문자열을 실제 boolean 값(true/false)으로 변환
            }

            response_body = json.dumps(response_data, ensure_ascii=False).encode('utf-8')

            # 7. 추출한 텍스트를 언리얼 엔진으로 다시 보내줍니다.
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(response_body)

        except Exception as e:
            # 과정 중 어떤 오류라도 발생하면, 500 오류와 함께 오류 메시지를 언리얼로 보냅니다.
            error_message = f"프록시 서버 오류: {e}"
            print(error_message) # 서버 로그에도 오류를 출력합니다.
            self.send_response(500)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(error_message.encode('utf-8'))

PORT = 8080

# 서버가 우리가 방금 위에서 정의한 ProxyHTTPRequestHandler 클래스를 사용하도록 지정합니다.
Handler = ProxyHTTPRequestHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"서버가 http://0.0.0.0:{PORT} 에서 시작되었습니다.")
    print("API 키를 성공적으로 로드했습니다.")
    print("서버를 중지하려면 Ctrl + C 를 누르세요.")
    httpd.serve_forever()