import json
import time
import boto3
from sense_hat import SenseHat
from datetime import datetime, timezone
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import os
import logging
import statistics
from dotenv import load_dotenv

load_dotenv()

prev_imu = {
    "acceleration": {"x": 0, "y": 0, "z": 0},
    "gyroscope": {"x": 0, "y": 0, "z": 0},
    "magnetometer": {"x": 0, "y": 0, "z": 0},
}

IOT_ENDPOINT = os.getenv("IOT_ENDPOINT")
THING_NAME = os.getenv("THING_NAME")
IOT_TOPIC = os.getenv("IOT_TOPIC")

CERTIFICATE_PATH = os.getenv("CERTIFICATE_PATH")
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")
ROOT_CA_PATH = os.getenv("ROOT_CA_PATH")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[
    logging.FileHandler("sensor_readings.log"),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

mqtt_client = AWSIoTMQTTClient(THING_NAME)
mqtt_client.configureEndpoint(IOT_ENDPOINT, 8883)
mqtt_client.configureCredentials(ROOT_CA_PATH, PRIVATE_KEY_PATH, CERTIFICATE_PATH)
mqtt_client.configureAutoReconnectBackoffTime(1, 32, 20)
mqtt_client.configureOfflinePublishQueueing(-1)
mqtt_client.configureConnectDisconnectTimeout(30)
mqtt_client.configureMQTTOperationTimeout(10)
logging.getLogger("AWSIoTPythonSDK.core").setLevel(logging.DEBUG)
try:
    logger.info(f"Attempting to connect to {IOT_ENDPOINT}:8883 as {THING_NAME}")
    mqtt_client.connect()
    logger.info("Connected to AWS IoT Core")
except Exception as e:
    logger.error(f"Failed to connect to AWS IoT Core: {str(e)}")

    exit(1)

sensor = SenseHat()
TEMP_CORRECTION_FACTOR = -5.4
HUMIDITY_CALIBRATION = 1.05
PRESSURE_CALIBRATION = 1.0
ALPHA = 0.2


def get_cpu_temperature():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read()) / 1000.0
    except Exception as e:
        logger.warning(f"Could not read CPU temperature: {e}")
        return None


def calibrate_temperature(raw_temp):
    cpu_temp = get_cpu_temperature()
    if cpu_temp is None:
        return raw_temp - TEMP_CORRECTION_FACTOR
    factor = (cpu_temp - raw_temp) / 5.466
    return raw_temp - factor


def low_pass_filter(new_value, prev_value):
    return (ALPHA * new_value) + ((1 - ALPHA) * prev_value)


def remove_outliers(values, threshold=2.0):
    if len(values) < 4:
        return values
    mean = statistics.mean(values)
    standev = statistics.stdev(values) if len(values) > 1 else 0
    if standev == 0:
        return values
    return [x for x in values if abs(x - mean) <= threshold * standev]

def read_sensor_data():
    global prev_imu
    try:
        temp_values = [sensor.get_temperature_from_humidity() for _ in range(10)]
        filtered_temp_values = remove_outliers(temp_values)
        raw_temp = statistics.median(filtered_temp_values) if filtered_temp_values else temp_values[0]
        temperature = calibrate_temperature(raw_temp)

        humidity_values = [sensor.get_humidity() for _ in range(10)]
        filtered_humidity = remove_outliers(humidity_values)
        humidity = round(statistics.median(filtered_humidity) * HUMIDITY_CALIBRATION, 2)

        pressure_values = [sensor.get_pressure() for _ in range(10)]
        filtered_pressure = remove_outliers(pressure_values)
        pressure = round(statistics.median(filtered_pressure) * PRESSURE_CALIBRATION, 2)

        acceleration = sensor.get_accelerometer_raw()
        gyroscope = sensor.get_gyroscope_raw()
        magnetometer = sensor.get_compass_raw()

        filtered_imu = {
            "acceleration": {
                "x": round(low_pass_filter(acceleration["x"], prev_imu["acceleration"]["x"]), 2),
                "y": round(low_pass_filter(acceleration["y"], prev_imu["acceleration"]["y"]), 2),
                "z": round(low_pass_filter(acceleration["z"], prev_imu["acceleration"]["z"]), 2),
            },
            "gyroscope": {
                "x": round(low_pass_filter(gyroscope["x"], prev_imu["gyroscope"]["x"]), 2),
                "y": round(low_pass_filter(gyroscope["y"], prev_imu["gyroscope"]["y"]), 2),
                "z": round(low_pass_filter(gyroscope["z"], prev_imu["gyroscope"]["z"]), 2),
            },
            "magnetometer": {
                "x": round(low_pass_filter(magnetometer["x"], prev_imu["magnetometer"]["x"]), 2),
                "y": round(low_pass_filter(magnetometer["y"], prev_imu["magnetometer"]["y"]), 2),
                "z": round(low_pass_filter(magnetometer["z"], prev_imu["magnetometer"]["z"]), 2),
            },
        }

        prev_imu.update(filtered_imu)
        current_time = int(time.time())
        ttl_time = current_time + (7 * 24 * 60 * 60)

        sensor_data = {
            "device_id": THING_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "temperature": round(temperature, 2),
            "humidity": humidity,
            "pressure": pressure,
            "imu": filtered_imu,
            "ttl_timestamp": ttl_time,
            "location": os.getenv("SENSOR_LOCATION", "bedroom_2")
        }

        logger.debug(f"Temperature: {sensor_data['temperature']} C, Humidity: {sensor_data['humidity']}%, Pressure: {sensor_data['pressure']} hPa")
        return sensor_data

    except Exception as e:
        logging.error(f"Error reading sensor data: {str(e)}")
        return None


try:
    logger.info("Starting sensor monitoring")
    sample_count = 0
    while True:
        sensor_data = read_sensor_data()
        if sensor_data:
            payload = json.dumps(sensor_data)
            mqtt_client.publish(IOT_TOPIC, payload, 1)

            sample_count += 1
            if sample_count % 12 == 0:
                logger.info(f"Published to AWS IoT: Temperature: {sensor_data['temperature']}C, Humidity: {sensor_data['humidity']}%")
            logging.info(f"Published to AWS IoT: {payload}")
        time.sleep(5)

except KeyboardInterrupt:
    logging.info("Stopping publishing")
except Exception as e:
    logging.error(f"Unexpected error: {str(e)}")
finally:
    mqtt_client.disconnect()
    logging.info("Disconnected from AWS IoT Core")
