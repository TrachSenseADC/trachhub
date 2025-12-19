

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

def calibrate(a, b, c, diff, gas_reading):
    tmt = transmittance(diff, gas_reading)
    abs = absorption(tmt)

    x = (math.log((1-(abs/a)))/(-b))**(1/c)

    # convert to mmHg
    if x < 0:
        return 0 # small tweak for now, this is an invalid reading since the trachsense is stationary
    return x * 7.6

# print(calibrate(A, B, C, 2118, GAS_READING))


    