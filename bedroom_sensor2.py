import time
import requests
from sense_hat import SenseHat
from datetime import datetime


MAIN_PI = "http://192.168.243.123:5000/api/sensor-data-upload"
ROOM_ID = "bedroom_2"
DEVICE_ID = "bedroom_pi_2"


sensor = SenseHat()

def collect_data():
    temperature = round(sensor.get_temperature(), 2)
    humidity = round(sensor.get_humidity(), 2)
    pressure = round(sensor.get_pressure(), 2)


    imu_data = {
        "acceleration": list(sensor.get_accelerometer_raw()),
        "gyroscope": list(sensor.get_gyroscope_raw()),
        "magnetometer": list(sensor.get_compass_raw())
    }

    data = {
        "temperature": temperature,
        "humidity": humidity,
        "pressure": pressure,
        "imu": imu_data,
        "room_id": ROOM_ID,
        "device_id": DEVICE_ID,
        "location": ROOM_ID.capitalize()
    }

    return data

def main_looping():
    while True:
        try:
            data = collect_data()
            response = requests.post(MAIN_PI, json=data)
            print(f"[{datetime.now()}] Sent data: {response.status_code}")
        except Exception as e:
            print(f"[{datetime.now()}] Failed to send data: {e}")

        time.sleep(5) # Sends data every 15 seconds

if __name__ == '__main__':
    main_looping()