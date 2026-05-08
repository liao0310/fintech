新增 VIP 門檻常數定義
VIP_THRESHOLD = 5_000_000

# 在相關判斷邏輯中使用 VIP_THRESHOLD 進行判斷
# 例如：
# if user.balance >= VIP_THRESHOLD:
#     user.is_vip = True
# else:
#     user.is_vip = False