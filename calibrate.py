

"""
diff - value we care about 
transmittance - diff / (gas/sensor readings) given 
absorption - 1 - transmittance 

coefficients - a, b, c -- provided 

x = c'th root of (ln (1 - ABS/a)/ -b)
ABS = a(1-e^-b(x^c))
"""
import math
from CONSTANTS import A, B, C, GAS_READING

transmittance = lambda diff, gas_reading: diff / gas_reading
absorption = lambda transmittance: 1 - transmittance
ABS = lambda a, b, c, x: a * (1 - math.exp(-b * (x ** c)))

def calibrate(a, b, c, diff, gas_reading, simple=False):
    if simple:
        return diff
    tmt = transmittance(diff, gas_reading)
    abs_val = absorption(tmt)

    # guard: if abs_val >= a, the log argument goes negative (produces complex)
    inner = 1 - (abs_val / a)
    if inner <= 0:
        return 0  # reading is outside the model's valid range

    print(inner)
    base = math.log(inner) / (-b)
    if base < 0:
        return 0  # negative base with fractional exponent would produce complex

    x = base ** (1 / c)

    # convert to mmHg
    return x * 7.6

# print(calibrate(A, B, C, 2118, GAS_READING))


    