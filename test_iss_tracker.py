import pytest
from iss_tracker import read_iss_data, now_epoch_speed, compute_speed, epoch_speed, epoch_data
import math
import requests

BASE_URL = "http://127.0.0.1:5000"
 # base url for testing purposes

# Sample mock data for testing
mock_iss_data = [
    {
        "EPOCH": "2025-063T12:00:00.000Z",
        "X": {"#text": "1000.0", "@units": "km"},
        "Y": {"#text": "2000.0", "@units": "km"},
        "Z": {"#text": "3000.0", "@units": "km"},
        "X_DOT": {"#text": "2.0", "@units": "km/s"},
        "Y_DOT": {"#text": "2.0", "@units": "km/s"},
        "Z_DOT": {"#text": "1.0", "@units": "km/s"},
    },
    {
        "EPOCH": "2025-063T12:01:00.000Z",
        "X": {"#text": "1100.0", "@units": "km"},
        "Y": {"#text": "2100.0", "@units": "km"},
        "Z": {"#text": "3100.0", "@units": "km"},
        "X_DOT": {"#text": "3.0", "@units": "km/s"},
        "Y_DOT": {"#text": "1.0", "@units": "km/s"},
        "Z_DOT": {"#text": "4.0", "@units": "km/s"},
    },
]

# Test: compute_speed()
def test_compute_speed(): # check for corect average speed
    # Given velocity components (2, 2, 1), speed should be:
    expected_speed = math.sqrt(2**2 + 2**2 + 1**2)
    assert compute_speed(2.0, 2.0, 1.0) == pytest.approx(expected_speed, rel=1e-3)

def test_compute_speed_zero():
    # Zero velocity should return 0 speed
    assert compute_speed(0.0, 0.0, 0.0) == 0.0

# Test: read_iss_data()
def test_read_iss_data(): # check if it returns correct list of dicts:
    """ Test /epochs route to check response status and format """
    response = requests.get(f"{BASE_URL}/epochs")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list) or isinstance(json_data, dict)  # Ensure it's a list or error dict

    if isinstance(json_data, list):
        assert all(isinstance(item, dict) for item in json_data)  # Ensure each item is a dictionary
    elif isinstance(json_data, dict):
        assert "error" in json_data  # Ensure error response has "error" key

def test_read_iss_data_with_params():
    """ Test /epochs with limit and offset parameters """
    response = requests.get(f"{BASE_URL}/epochs?limit=5&offset=2")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list)
    assert len(json_data) <= 5  # Ensure it respects the limit

def test_read_iss_data_invalid_params():
    """ Test /epochs with invalid parameters """
    response = requests.get(f"{BASE_URL}/epochs?limit=abc")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, dict)
    assert "error" in json_data  # Ensure error response exists

# Test: data_for_epoch
def test_valid_epoch():
    """ Test /epochs/<epoch> with a valid epoch """
    response_epochs = requests.get(f"{BASE_URL}/epochs")
    assert response_epochs.status_code == 200
    epochs_list = response_epochs.json()

    if epochs_list:  # Ensure we have data to test
        sample_epoch = epochs_list[0]["EPOCH"]  # Pick first epoch
        response = requests.get(f"{BASE_URL}/epochs/{sample_epoch}")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)  # Ensure response is a dictionary
        assert "EPOCH" in response.json()  # Ensure the response contains the correct key

def test_invalid_epoch():
    """ Test /epochs/<epoch> with an invalid epoch """
    response = requests.get(f"{BASE_URL}/epochs/INVALID_EPOCH")
    assert response.status_code == 200  # API should return an error dictionary, but not crash
    json_data = response.json()
    assert isinstance(json_data, dict)
    assert "error" in json_data  # Ensure it returns an error message

# Test: now_epoch_speed()
### NOTE FOR THE TA; I ONLY HAVE ONE TEST FOR THIS FUNC. BECAUSE I DIDN'T KNOW HOW TO SIMULATE read_iss_data() failing byitself in this case.
def test_now_route():
    """ Test /now route to check response status and format """
    response = requests.get(f"{BASE_URL}/now")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, dict)  # Ensure response is a dictionary
    assert "now_EPOCH" in json_data # Ensure "now_EPOCH" key exists

# Test: speed_for_epoch():
def test_speed_for_valid_epoch():
    """ Test /epochs/<epoch>/speed with a valid epoch """
    response_epochs = requests.get(f"{BASE_URL}/epochs")
    assert response_epochs.status_code == 200
    epochs_list = response_epochs.json()

    if epochs_list:  # Ensure we have data to test
        sample_epoch = epochs_list[0]["EPOCH"]  # Pick first epoch
        response = requests.get(f"{BASE_URL}/epochs/{sample_epoch}/speed")
        assert response.status_code == 200
        json_data = response.json()
        assert isinstance(json_data, dict)  # Ensure response is a dictionary
        assert "EPOCH" in json_data  # Ensure "EPOCH" key exists

def test_speed_for_invalid_epoch():
    """ Test /epochs/<epoch>/speed with an invalid epoch """
    response = requests.get(f"{BASE_URL}/epochs/INVALID_EPOCH/speed")
    assert response.status_code == 200  # API should return an error dictionary, not crash
    json_data = response.json()
    assert isinstance(json_data, dict)
    assert "error" in json_data  # Ensure error message is returned

def test_epoch_location_valid():
    """
    Test that /epochs/<epoch>/location returns a valid location dictionary
    for a valid EPOCH.
    """
    # Get a valid epoch from the /epochs route.
    response = requests.get(f"{BASE_URL}/epochs")
    assert response.status_code == 200
    epochs_data = response.json()

    if isinstance(epochs_data, list) and len(epochs_data) > 0:
        sample_epoch = epochs_data[0]["EPOCH"]
    else:
        pytest.skip("No valid epoch data available to test location route.")

    # Now call the location endpoint for this epoch.
    response_loc = requests.get(f"{BASE_URL}/epochs/{sample_epoch}/location")
    assert response_loc.status_code == 200
    loc_data = response_loc.json()

    # Check that the returned data is a dict and contains the required keys.
    expected_keys = ["latitude", "longitude", "altitude", "Nearest_Geolocation"]
    for key in expected_keys:
        assert key in loc_data, f"Expected key '{key}' in location response"

    # Optionally, ensure latitude, longitude, and altitude are numbers.
    assert isinstance(loc_data["latitude"], (float, int))
    assert isinstance(loc_data["longitude"], (float, int))
    assert isinstance(loc_data["altitude"], (float, int))

def test_epoch_location_invalid():
    """
    Test that /epochs/<epoch>/location returns an error when an invalid EPOCH is provided.
    """
    invalid_epoch = "9999-999T99:99:99.999Z"
    response_loc = requests.get(f"{BASE_URL}/epochs/{invalid_epoch}/location")
    assert response_loc.status_code == 200
    loc_data = response_loc.json()
    assert "error" in loc_data, "Expected an error for an invalid EPOCH"
