import asyncio
import google.generativeai as genai
import os
import google.generativeai.types as types

# --- CẤU HÌNH ---
# Tên file chứa list key của mày
INPUT_FILE = "gemini.txt"
# Tên file sẽ lưu kết quả
OUTPUT_FILE = "checked_keys_result.txt"
# Tao sửa dòng này để dùng model test Pro ổn định hơn
TEST_MODEL = "gemini-2.5-flash" 

async def check_single_key(key, semaphore):
    """Checks the status of a single API key without blind .text access."""
    key = key.strip()
    if not key:
        return None

    async with semaphore:
        try:
            # Cấu hình key
            genai.configure(api_key=key)
            model = genai.GenerativeModel(TEST_MODEL)
            
            # Gửi request test cực ngắn
            # Sử dụng safety_settings để tránh bị block nhầm
            response = await model.generate_content_async(
                "hi",
                generation_config=types.GenerationConfig(max_output_tokens=1),
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                ]
            )
            
            # --- ĐOẠN NÀY ĐÃ FIX LỖI CỦA MÀY ---
            # Không dùng response.text trực tiếp. Hãy kiểm tra candidate.
            if response.candidates:
                candidate = response.candidates[0]
                
                # Kiểm tra lý do kết thúc (finish_reason)
                # STOP = Thành công, các lý do khác = Bị chặn
                if candidate.finish_reason.name == "STOP":
                    # Key sống, test thành công
                    return (key, "ACTIVE")
                elif candidate.finish_reason.name in ["SAFETY", "RECITATION"]:
                    # Key sống, nhưng nội dung test bị chặn
                    return (key, f"ACTIVE (Generated content blocked by {candidate.finish_reason.name})")
                else:
                    return (key, f"ACTIVE (Finish Reason: {candidate.finish_reason.name})")
            else:
                # Nếu không có candidate, có thể prompt bị chặn hoàn toàn
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    return (key, f"ACTIVE (Prompt Blocked: {response.prompt_feedback.block_reason.name})")
                return (key, "UNKNOWN (Generated Nothing/Empty)")

        except Exception as e:
            error_msg = str(e).lower()
            
            # Phân loại lỗi mạng/server/xác thực
            if "api_key_invalid" in error_msg or "invalid api key" in error_msg:
                return (key, "DEAD (Invalid)")
            elif "429" in error_msg or "resource_exhausted" in error_msg:
                # Key sống nhưng hết quota hôm nay
                return (key, "ACTIVE (Quota Exceeded)")
            elif "403" in error_msg or "permission_denied" in error_msg:
                # Key đúng, project đúng, nhưng bị Google chặn project
                return (key, "DEAD (Permission Denied/Blocked Project)")
            else:
                # In lỗi mạng cụ thể ra màn hình để debug nếu bị chặn IP VN
                print(f"⚠️ Lỗi mạng với Key {key[:5]}...: {str(e)[:100]}") 
                return (key, f"UNKNOWN ERROR (Network/Proxy?)")

async def main():
    # 1. Đọc danh sách key
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Không tìm thấy file input: {INPUT_FILE}")
        print(f"👉 Hãy tạo file {INPUT_FILE} và dán đống key vào đó.")
        return

    with open(INPUT_FILE, "r") as f:
        keys = f.readlines()

    keys = [k.strip() for k in keys if k.strip()] # Làm sạch list
    total_keys = len(keys)

    if total_keys == 0:
        print(f"❌ File {INPUT_FILE} trống.")
        return

    print(f"🔍 Bắt đầu check {total_keys} keys bằng model {TEST_MODEL}. Code đã fix lỗi response.text.")
    print(f"⚠️ Nếu thấy 'Lỗi mạng' hàng loạt, hãy bật VPN và chạy lại.")

    # 2. Thiết lập check đồng thời (Semaphore)
    semaphore = asyncio.Semaphore(10) 
    tasks = [check_single_key(key, semaphore) for key in keys]

    # 3. Chạy tất cả task và gom kết quả
    results = await asyncio.gather(*tasks)

    # 4. Phân loại và ghi kết quả
    active_keys = []
    dead_keys = []
    unknown_keys = []

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("--- KẾT QUẢ CHECK GOOGLE AI STUDIO API KEYS (Fixed Code) ---\n\n")
        
        for result in results:
            if not result: continue
            key, status = result
            # Ghi key đã ẩn một phần để bảo mật
            f.write(f"Key: {key[:10]}...{key[-5:]} | Status: {status}\n")
            
            if "ACTIVE" in status:
                active_keys.append(result)
            elif "DEAD" in status:
                dead_keys.append(result)
            else:
                unknown_keys.append(result)

        f.write("\n--- TỔNG KẾT ---\n")
        f.write(f"✅ SỐNG (Dùng được): {len(active_keys)}\n")
        f.write(f"💀 CHẾT (Bỏ đi): {len(dead_keys)}\n")
        f.write(f"❓ KHÔNG RÕ (Check mạng): {len(unknown_keys)}\n")

    print(f"\n✅ Đã check xong!")
    print(f"📊 Tổng kết: {len(active_keys)} Sống / {len(dead_keys)} Chết / {len(unknown_keys)} Không rõ.")
    print(f"📝 Kết quả chi tiết đã lưu vào file: {OUTPUT_FILE}")

# Chạy chương trình async
if __name__ == "__main__":
    asyncio.run(main())