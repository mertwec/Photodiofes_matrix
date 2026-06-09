from config import cfg

def sum_power(data:list, v_min = cfg.S_VAL_MIN):
    return sum([v_min - i for i in data])


i0 = [
        488.9,
        579.2,
        643.8,
        430.1
      ]

i1 = [
        2403.2,
        2771.1,
        35.4,
        31.6
      ]

i2 = [
        48.9,
        27.1,
        2610.8,
        2576.6
      ]


print(f"P0 = {sum_power(i0)}")
print(f"P1 = {sum_power(i1)}")
print(f"P2 = {sum_power(i2)}")
