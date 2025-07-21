from flask import Flask, request, jsonify
import requests
import json
import os
import logging

# Flask 앱 및 로깅 설정
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Vercel 환경 변수에서 API 키를 가져옵니다.
API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini API 엔드포인트 URL
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}" if API_KEY else None

# LLM에게 보낼 프롬프트 '틀'입니다.
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

@app.route('/api/proxy', methods=['POST'])
def handle_proxy():
    if not GEMINI_API_URL:
        app.logger.error("CRITICAL: GOOGLE_API_KEY is not set.")
        return jsonify({"error": "API key is not configured on the server."}), 500

    try:
        client_data = request.get_json()
        if not client_data:
            return jsonify({"error": "Invalid JSON format in request body"}), 400

        question_sentence = client_data.get('question')
        student_answer = client_data.get('answer')

        if not question_sentence or not student_answer:
            return jsonify({"error": "Request body must contain 'question' and 'answer' fields."}), 400

        final_prompt = PROMPT_TEMPLATE.format(QuestionSentence=question_sentence, StudentAnswer=student_answer)
        
        gemini_payload = {
            "contents": [{"parts": [{"text": final_prompt}]}]
        }

        headers = {'Content-Type': 'application/json'}
        response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(gemini_payload), timeout=25)
        
        app.logger.info(f"Gemini API Response Status: {response.status_code}")
        app.logger.info(f"Gemini API Response Body: {response.text}")

        response.raise_for_status()

        response_json = response.json()

        if 'candidates' not in response_json or not response_json['candidates']:
            app.logger.error(f"Gemini response is missing 'candidates'. Full response: {response.text}")
            return jsonify({"error": "AI model returned an empty or invalid response.", "details": "Response missing 'candidates'"}), 502
        
        first_candidate = response_json['candidates'][0]
        
        # 안전성 검사: finishReason이 'SAFETY' 등 다른 이유로 막혔는지 확인
        if 'finishReason' in first_candidate and first_candidate['finishReason'] != 'STOP':
            app.logger.error(f"Gemini generation stopped for reason: {first_candidate['finishReason']}. Full candidate: {first_candidate}")
            return jsonify({"error": "AI content generation was blocked.", "details": f"Reason: {first_candidate.get('finishReason')}"}), 502

        if 'content' not in first_candidate or 'parts' not in first_candidate['content'] or not first_candidate['content']['parts']:
            app.logger.error(f"Gemini response is missing 'content' or 'parts'. Full candidate: {first_candidate}")
            return jsonify({"error": "AI model returned an invalid content structure.", "details": "Response missing 'content' or 'parts'"}), 502

        result_text = first_candidate['content']['parts'][0].get('text', '')

        parts = result_text.strip().split('\n')
        display_message = parts[0] if len(parts) > 0 and parts[0] else "메시지를 받지 못했습니다."
        is_correct_str = parts[1] if len(parts) > 1 and parts[1] else "False"

        response_data = {
            "message": display_message,
            "isCorrect": is_correct_str.strip().lower() == 'true'
        }

        return jsonify(response_data)

    except requests.exceptions.Timeout:
        app.logger.error("Request to Google Gemini API timed out.")
        return jsonify({"error": "The request to the AI model timed out."}), 504

    except requests.exceptions.RequestException as e:
        error_details = str(e)
        if e.response is not None:
            error_details = e.response.text
        app.logger.error(f"Error from Google Gemini API: {error_details}")
        return jsonify({"error": "Failed to get response from AI model.", "details": error_details}), 502
        
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred."}), 500