if user_aum > 5_000_000:
    status = STATUS_VIP_A
elif user_aum > 1_000_000:
    status = STATUS_VIP_B
else:
    status = STATUS_STANDARD