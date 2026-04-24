from openai import OpenAI


BASE_URL = "https://llm.wokushop.com/v1"
client = OpenAI(
    api_key="sk-bYYKTjtv0mePlRlw2jTDF5PfAssrlgozZSEC3OEAdLsSXh0u",
    base_url=BASE_URL,
)

def chat_with_openai():
    try:
        # Tạo yêu cầu gửi đến mô hình
        response = client.chat.completions.create(
            model="qwen-turbo-2025-07-15", # Bạn có thể đổi thành "gpt-4" hoặc "gpt-4o"
            messages=[
                {"role": "system", "content": "Bạn là một trợ lý ảo nhiệt tình và thân thiện."},
                {"role": "user", "content": "Xin chào! Hãy viết cho tôi một câu thơ ngắn về bầu trời."}
            ],

        )
        
        # In kết quả trả về
        print("Trợ lý:", response.choices[0].message.content)
        
    except Exception as e:
        print(f"Đã xảy ra lỗi: {e}")

if __name__ == "__main__":
    chat_with_openai()