# File: Smart_Throttle_Analog_output_rx0.py
# By: Richard R. Vasquez
# Date: 10/19/2024
#
# Notes: This version is almost perfected. Still needs improvements. PWM output only.
# Analog output now works. The MINPWM and MAXPWM were clipping the signal
# The Brake signal doesn't take it out of hold mode! I need to work on that. 
# For use with Throttle ID #2
# The ISR and main() were swapped because it made more sense to have the more complex
# function in main() and the simple update function in the ISR. 
#
# Operation: 
# Map the analog value to the PWM duty cycle (0-65535)
# Assuming the analog range is 0-3.3V (for 3.3V ADC reference)

# 10% of 65535 = 6553.5 approximately 6554
# 5% of 3277 (approximately)
# Observation of throttle: Full speed = 3.84 volts, Min speed = 0.76 volts
# Used 0.75 scale down, since 3.8 > 3.3 range of ADC reference voltage.
# Scaled down 0.75x Throttle: Full speed = 2.88 volts, Min speed = 0.566 volts
# ADC: 50.355 uV/step
# Delta steps: 57195-11250 = 45945   This is the range of the throttle.
# Delta PWM = 6554-3277 = 3277   100% - 50% = 50%   This is for the output.
#
# OPTION 1: This is for a PWM output.
# Full throttle range corresponds to PWM range from 5% to 10% (50Hz, 1mS to 2mS) 
# Slope: m = 3227/45945 = 0.070237 = 1/14.2377
# Offet: b = y - m*x = 3227 - (11250/14.2377) = 3277 - 790.156 = 2436.84
#
# OPTION 2: This is for an analog output to support low-cost ESC's
# We can easily convert PWM to analog using a low-pass RC filter. Fc = 5Hz, R = 1Mohm, C = 0.2uF
# We just feed the ADC value to the PWM with no changes to recreate the analog singnal.
# Slope_A: m = 1 and Offet_A: b = 0

import machine
import utime
import array


# Predefine constants
STOPPED = 12153          # Throttle min. voltage = 0.612V
FULLSPEED = 60927        # Throttle min. voltage = 3.068V
#MINPWM = 3277            # PWM set to 5%    (PWM mode)
#MAXPWM = 6554            # PWM set to 10%   (PWM mode)
MINPWM = STOPPED            # PWM set to 5%    (PWM mode)
MAXPWM = FULLSPEED            # PWM set to 10%   (PWM mode)
ONE_MPH = 13895          # ADC value for 1 MPH
THREE_MPH = 16163        # ADC value for 3 MPH
DELTA_1MPH = 1742        # ADC threshold for 1 MPH change
LED_ON = 0               # LED is active low, On
LED_OFF = 1              # LED is active low, Off

# Program stability constants
PWMFREQ = 50             # PWM frequency = 50Hz
ISR_FREQ = 10            # ISR frequency = 10Hz
ARRAY_SIZE = 100         # 10 seconds * ISR_FREQ = 100 samples 

# Mode constants
IDLE = 0                 # Idle mode
RUN = 1                  # Run mode
HOLD = 2                 # Hold mode
BRAKE_ON = 0             # Brake input: active low

# For PWM Output
#SLOPE = 1 / 14.884       # Throttle response slope for PWM output.
#OFFSET = 2461            # Throttle response offset for PWM output.
SLOPE = 1                # Throttle response slope for Analog output. This doesn't work right!
OFFSET = 0               # Throttle response offset for Analog output.

# RP2040 Zero pin assignments 
ADC_PIN = 26             # ADC on GP26 (Throttle Input)
PWM_PIN = 0              # PWM on GP0 (Throttle Output)
BRAKE_PIN = 1            # Brake sense on GP1 (Brake connector signal)
LED_PIN = 8              # GPIO 8 for LED when mode = HOLD

# Predefine devices
adc = machine.ADC(machine.Pin(ADC_PIN))  # ADC on GP26
pwm = machine.PWM(machine.Pin(PWM_PIN))  # PWM on GP0 (Throttle Output)
pwm.freq(PWMFREQ)  # Set PWM frequency to 50 Hz (20ms period)

# Initialize array and variables
adc_array = array.array('i', [0]*ARRAY_SIZE)  # Circular array to hold 10 ADC samples
index = 0             # Array index (0-9)
avg = 0               # Average value of array elements
mode = IDLE           # Start in IDLE mode
speed = STOPPED       # Default speed
hold_speed = STOPPED  # Default hold speed
adc_value = 0         # Latest ADC value
duty_cycle = MINPWM   # Initial duty cycle
#adc_value = 0         # Throttle value from ADC

# Brake input pin on GP1 with internal pull-up resistor
brake_pin = machine.Pin(BRAKE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)

# LED pin configuration on GPIO 8
led_pin = machine.Pin(LED_PIN, machine.Pin.OUT)

# Function to read the ADC value (Throttle input)
def read_adc():
    return adc.read_u16()

# Function to update the PWM output
def update_pwm(duty_cycle):
    pwm.duty_u16(duty_cycle)

# Function to flush the array (reset all values to 0)
def flush_array():
    global adc_array
    adc_array = array.array('i', [0]*ARRAY_SIZE)  # Reset array to all 0's

# Function to calculate average of the array
def calculate_average():
    return sum(adc_array) // len(adc_array)

# New ISR (formerly the main loop's speed and PWM updates)
def timer_isr(timer):
    global mode, speed, duty_cycle
    
    adc_value = read_adc()  # Continuously update the ADC value
    # Update speed and PWM duty cycle based on mode
    if mode == IDLE:  # IDLE mode
        speed = STOPPED
    elif mode == HOLD:  # HOLD mode
        speed = hold_speed
    else:  # RUN mode
        speed = adc_value

    # Convert speed to PWM duty cycle
    duty_cycle = int(speed * SLOPE + OFFSET)
    print("Duty Cycle: ", duty_cycle)    

    # Constrain duty cycle to the 5% - 10% range
    if duty_cycle < MINPWM:
        duty_cycle = MINPWM
    elif duty_cycle > MAXPWM:
        duty_cycle = MAXPWM

    # Update PWM output
    update_pwm(duty_cycle)

# New main loop (formerly the ISR logic, but now loops forever)
def main():
    global mode, index, hold_speed, avg, target, adc_value

    # Main loop with 0.1S delay
    led_pin.value(LED_OFF)  # Turn off the LED to start
    print("IDLE mode")
    while True:
        # If brake is applied, go to IDLE mode
        utime.sleep(0.1)
        adc_value = read_adc()  # Continuously update the ADC value
        # print("ADC: ", adc_value)   
        if brake_pin.value() == 0:  # Brake is active (IDLE mode)
            mode = IDLE
            print("IDLE mode")
        else:
            # Mode transitions and ADC handling
            if mode == IDLE and adc_value > THREE_MPH:  # Exiting IDLE mode                
                mode = RUN  # Switch to RUN mode
                print("RUN mode")
            elif mode == HOLD and adc_value > target:  # Exiting HOLD mode
                mode = RUN  # Switch back to RUN mode
                print("RUN mode")
                led_pin.value(LED_OFF)  # Turn off the LED when leaving HOLD mode
                flush_array()
            elif mode == HOLD and adc_value < ONE_MPH:
                target = THREE_MPH
            else:
                # Must be in RUN mode by default
                adc_array[index] = adc_value  # Add current ADC value to array
                index = (index + 1) % ARRAY_SIZE # Circular buffer logic
                avg = calculate_average()  # Calculate average

                # Check if speed stabilizes within 1 MPH to enter HOLD mode
                if (abs(adc_value - avg) < DELTA_1MPH) and (avg > ONE_MPH):
                    mode = HOLD  # Enter HOLD mode
                    print("HOLD mode, Avg: ", avg, "ADC: ", adc_value)
                    led_pin.value(LED_ON)  # Turn on the LED when entering HOLD mode
                    hold_speed = adc_value
                    target = adc_value + ONE_MPH
                    flush_array()

# Timer to run the new ISR
timer = machine.Timer()
timer.init(freq=ISR_FREQ, mode=machine.Timer.PERIODIC, callback=timer_isr)

# Start the new main loop (formerly the ISR logic, now loops forever)
main()


