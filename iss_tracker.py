# USE OF LLM: Docstrings and partial commentings.
#!/usr/bin/env python3
import time
from astropy import coordinates
from astropy import units
from astropy.time import Time
from geopy.geocoders import Nominatim # for geoposition calculation
import requests
import xmltodict # converting NASA ISS Data format
import math
from typing import List, Dict, Tuple
import logging
from flask import Flask, request
import json
import redis


# create Flask object
app = Flask(__name__)
# create Redis client
rd = redis.Redis(host='127.0.0.1', port=6379, db = 7) # TODO: change the host to "redis-db" later
# logging config:
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


@app.route('/epochs', methods = ['GET'])
def read_iss_data() -> List[dict]:
    """
    Fetches ISS state vector data from a given URL and stores it in Redis.

    If Redis is empty, the function populates it with the latest state vectors.
    If Redis already has data, it only updates the new state vectors.

    Returns:
        list: A list of state vector dictionaries retrieved from Redis.
              If an error occurs, returns {'error': '...'}.
    """

    url = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml"
    
    try:
        # retrieve the object from the given URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx, 5xx)
        # Parse XML to dictionary
        data = xmltodict.parse(response.text)
        # Navigate to state vectors
        state_vectors = data['ndm']['oem']['body']['segment']['data']['stateVector']
        # send if no state_vectors
        if not state_vectors:
            logging.warning("No state vectors found in the data.")
            return {"error": "No ISSS StateVectors found"} 
    except requests.RequestException as e:
        logging.error(f"Network error while fetching ISS data: {e}")
        return {'error':'failed to fetch iss data'}
    except (KeyError, xmltodict.expat.ExpatError) as e:
        logging.error(f"Error parsing XML data: {e}")
        return {'error':'error parsing XML data'}
    
    # store the entire list into Redis DB:
    for sv in state_vectors:
        # retrieve EPOCH to be used for keys
        epoch = sv['EPOCH']
        
        # check if EPOCH key already exists in the DB:
        if not rd.exists(epoch):
            print(f"adding new epoch: {epoch}")
            # set each key-value pair in the database
            rd.set(epoch, json.dumps(sv))
            # store EPOCH keys for later
            rd.rpush('iss_keys', epoch) # this is a list of EPOCH keys
        else:
            # Compare stored data and update if different
            stored_data = json.loads(rd.get(epoch))
            if stored_data != sv:
                logging.info(f"Updating existing EPOCH: {epoch}")
                rd.set(epoch, json.dumps(sv))
            else:
                print("data already exists in the DB")
                logging.info(f"the data already exists!")
   
   # number of total elements to be returned
    limit = request.args.get('limit', len(state_vectors))
    try: limit = int(limit)
    except ValueError: return {'error':"limit parameter must be an integer"}
    
    # how many to skip initially
    offset = request.args.get('offset', 0)
    try: offset = int(offset)
    except ValueError: return {'error':"offset parameter must be an integer"}
    
    if offset >= len(state_vectors): return {'error': 'offset param. out of range.'}
    
    # retrieve all the data from the DB
    epoch_keys = rd.lrange('iss_keys', 0, -1)
    state_vectors = [json.loads(rd.get(epoch_key)) for epoch_key in epoch_keys]

    # apply paramters and return
    return state_vectors[offset:offset+limit]

@app.route('/epochs/<epoch>', methods=["GET"])
def epoch_data(epoch:str) -> dict:
    """
        Retrieve state vector data for a specific EPOCH.

        Args:
            epoch (str): The timestamp of the requested EPOCH.

        Returns:
            dict: The state vector data if EPOCH is found.
                  If not found, returns {'error': 'No matching EPOCH'}.
    """

    # check if EPCOH exists in the redis db:
    if not rd.exists(epoch):
        return {'error': 'No matching EPOCH'}
    else:
        return json.loads(rd.get(epoch))

 
@app.route('/now', methods=["GET"])
def now_epoch_speed() -> dict:
    """
    Finds the ISS state vector closest to the current UTC time and returns its EPOCH and instant speed.

    Returns:
        dict: {
            "EPOCH": str,  # Closest matching EPOCH timestamp
            "instant speed": float  # Computed speed at the closest EPOCH
        }
    """
    # get the current UTC time in seconds
    now_time_in_seconds = time.mktime(time.gmtime())
    # place holder to track minimum time diff: 
    min_time_diff = float("inf")
    # EPOCH format
    value_format = '%Y-%jT%H:%M:%S.%fZ'
    
    # retreive all the EPOCH keys from redis DB:
    epoch_keys = rd.lrange('iss_keys', 0, -1)
    # in case the DB is empty:
    if not epoch_keys:
        return {'error': 'Database is empty.'}

    closest_epoch_key = None

    # iterate over all keys to find the closes time_value against curr_time_in_seconds
    for epoch_key in epoch_keys:
        # for each epoch key,  turn the time to seconds since Unix EPOCH
        dict_time_in_seconds = time.mktime(time.strptime(epoch_key.decode("utf-8"), value_format))
        # compute time difference compared to NOW:
        latest_time_diff = now_time_in_seconds - dict_time_in_seconds
        
        # figure out if the differene is the minimum.
        if abs(latest_time_diff) < min_time_diff:
            closest_epoch_key = epoch_key.decode("utf-8")
            min_time_diff = latest_time_diff
    
    now_speed = epoch_speed(closest_epoch_key)

    return now_speed
    
def compute_speed(x_velocity: float, y_velocity: float, z_velocity: float) -> float:
    """
    Computes the instantaneous speed given velocity components.

    Args:
        x_velocity (float): Velocity component along the X-axis (km/s).
        y_velocity (float): Velocity component along the Y-axis (km/s).
        z_velocity (float): Velocity component along the Z-axis (km/s).

    Returns:
        float: The computed speed in km/s.
    """
    return math.sqrt(x_velocity**2 + y_velocity**2 + z_velocity**2)


@app.route('/epochs/<epoch>/speed', methods=['GET'])
def epoch_speed(epoch:str)-> dict:
    """
    Computes the speed for a defined EPOCH.

    Args:
        epoch (str): The timestamp of the requested EPOCH.

    Returns:
        dict: {
            "EPOCH": str,  # The requested EPOCH timestamp
            "instant speed": float  # Computed speed at this EPOCH
        }
        If the EPOCH is not found, returns {'error': 'No matching EPOCH'}.
    """
    # get the state vector for that specific EPOCH
    state_vec = epoch_data(epoch)
    
    # check for any wrong EPOCH errors.
    if "error" in state_vec:
        return state_vec

    try: # let's try getting each velocity component
        x_dot = state_vec['X_DOT']['#text']
        y_dot = state_vec['Y_DOT']['#text']
        z_dot = state_vec['Z_DOT']['#text']
    except KeyError:
        return {'error':"Failed to extract velocity components, KeyError."}
    except TypeError:
        return {'error': "TypeError, failed to get velocity components."}

    # compute instant speed using existing compute_speed() func.
    instant_speed = compute_speed(float(x_dot), float(y_dot), float(z_dot))

    return {'EPOCH':epoch, 'instant speed':instant_speed}


def compute_location_astropy(sv: dict) -> tuple:
    """
    Converts the ISS state vector from GCRS (Geocentric Celestial Reference System)
    to ITRS (International Terrestrial Reference System) using Astropy.

    Args:
        sv (dict): The state vector containing position (X, Y, Z) and EPOCH.

    Returns:
        tuple: (latitude, longitude, altitude) of ISS in degrees and km.
        If an error occurs, returns {'error': '...'}.
    """
    # try accessing 3D coordinate elemnts:
    try:
        x = float(sv['X']['#text'])
        y = float(sv['Y']['#text'])
        z = float(sv['Z']['#text'])
    # handle any key errors, type errors or value errors
    except (KeyError, TypeError, ValueError) as e:
        print(f"Error extracting coordinates: {e}")
        return None, None, None
    
    # assumes epoch is in format '2024-067T08:28:00.000Z'
    try: # Convert EPOCH format from NASA's "%Y-%jT%H:%M:%S.%fZ" to "%Y-%m-%d %H:%M:%S.%f"
        this_epoch=time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(sv['EPOCH'][:-5], '%Y-%jT%H:%M:%S'))
    except ValueError as e:
        print(f"Error parsing EPOCH time: {e}")
        return None, None, None
    
    # Convert ISS position from GCRS to ITRS (Earth coordinates)
    cartrep = coordinates.CartesianRepresentation([x, y, z], unit=units.km)
    gcrs = coordinates.GCRS(cartrep, obstime=this_epoch)
    itrs = gcrs.transform_to(coordinates.ITRS(obstime=this_epoch))
    loc = coordinates.EarthLocation(*itrs.cartesian.xyz)

    return loc.lat.value, loc.lon.value, loc.height.value

def compute_nearest_geolocation(lat: float, lon: float):
    """
    Returns the nearest geoposition/geolocation for given latitude and longitude.
    """
    geocoder = Nominatim(user_agent='iss_tracker')
    geoloc = geocoder.reverse((lat, lon), zoom=15, language='en')
    
    # if geoloc returns None (When the ISS is over the ocean), increment the zoom till it is NOT None.
    zoom_level = 15
    while geoloc == None:
        zoom_level += 1
        geoloc = geocoder.reverse((lat, lon), zoom=zoom_level, language='en')
    
    address = geoloc['address']

    return 

@app.route('/epochs/<epoch>/location', methods = ['GET'])
def epoch_location(epoch: str) -> dict:
    """
    Returns latitude, longitude, altitude, and geoposition for a given <epoch>.
    """
    state_vec = epoch_data(epoch) # get the state vector for given EPOCH
    
    # get latitude, longitude, and altitude values
    lat, lon, alt = compute_location_astropy(state_vec)
    # check if the function returned any non-floating values:
    if lat == None:
        return {'error': 'Failed to Extract Latitude, Longitude, and Height.'}
    
    # get geoPosition




if __name__ == "__main__":
    #main()
    app.run(debug=True, host="0.0.0.0")
# USE OF LLM: Docstrings and partial commentings.
#!/usr/bin/env python3
import time
from astropy import coordinates
from astropy import units
from astropy.time import Time
from geopy.geocoders import Nominatim # for geoposition calculation
import requests
import xmltodict # converting NASA ISS Data format
import math
from typing import List, Dict, Tuple
import logging
from flask import Flask, request
import json
import redis


# create Flask object
app = Flask(__name__)
# create Redis client
rd = redis.Redis(host='127.0.0.1', port=6379, db = 7) # TODO: change the host to "redis-db" later
# logging config:
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


@app.route('/epochs', methods = ['GET'])
def read_iss_data() -> List[dict]:
    """
    Fetches ISS state vector data from a given URL and stores it in Redis.

    If Redis is empty, the function populates it with the latest state vectors.
    If Redis already has data, it only updates the new state vectors.

    Returns:
        list: A list of state vector dictionaries retrieved from Redis.
              If an error occurs, returns {'error': '...'}.
    """

    url = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml"
    
    try:
        # retrieve the object from the given URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx, 5xx)
        # Parse XML to dictionary
        data = xmltodict.parse(response.text)
        # Navigate to state vectors
        state_vectors = data['ndm']['oem']['body']['segment']['data']['stateVector']
        # send if no state_vectors
        if not state_vectors:
            logging.warning("No state vectors found in the data.")
            return {"error": "No ISSS StateVectors found"} 
    except requests.RequestException as e:
        logging.error(f"Network error while fetching ISS data: {e}")
        return {'error':'failed to fetch iss data'}
    except (KeyError, xmltodict.expat.ExpatError) as e:
        logging.error(f"Error parsing XML data: {e}")
        return {'error':'error parsing XML data'}
    
    # store the entire list into Redis DB:
    for sv in state_vectors:
        # retrieve EPOCH to be used for keys
        epoch = sv['EPOCH']
        
        # check if EPOCH key already exists in the DB:
        if not rd.exists(epoch):
            print(f"adding new epoch: {epoch}")
            # set each key-value pair in the database
            rd.set(epoch, json.dumps(sv))
            # store EPOCH keys for later
            rd.rpush('iss_keys', epoch) # this is a list of EPOCH keys
        else:
            # Compare stored data and update if different
            stored_data = json.loads(rd.get(epoch))
            if stored_data != sv:
                logging.info(f"Updating existing EPOCH: {epoch}")
                rd.set(epoch, json.dumps(sv))
            else:
                print("data already exists in the DB")
                logging.info(f"the data already exists!")
   
   # number of total elements to be returned
    limit = request.args.get('limit', len(state_vectors))
    try: limit = int(limit)
    except ValueError: return {'error':"limit parameter must be an integer"}
    
    # how many to skip initially
    offset = request.args.get('offset', 0)
    try: offset = int(offset)
    except ValueError: return {'error':"offset parameter must be an integer"}
    
    if offset >= len(state_vectors): return {'error': 'offset param. out of range.'}
    
    # retrieve all the data from the DB
    epoch_keys = rd.lrange('iss_keys', 0, -1)
    state_vectors = [json.loads(rd.get(epoch_key)) for epoch_key in epoch_keys]

    # apply paramters and return
    return state_vectors[offset:offset+limit]

@app.route('/epochs/<epoch>', methods=["GET"])
def epoch_data(epoch:str) -> dict:
    """
        Retrieve state vector data for a specific EPOCH.

        Args:
            epoch (str): The timestamp of the requested EPOCH.

        Returns:
            dict: The state vector data if EPOCH is found.
                  If not found, returns {'error': 'No matching EPOCH'}.
    """

    # check if EPCOH exists in the redis db:
    if not rd.exists(epoch):
        return {'error': 'No matching EPOCH'}
    else:
        return json.loads(rd.get(epoch))

 
@app.route('/now', methods=["GET"])
def now_epoch_speed() -> dict:
    """
    Finds the ISS state vector closest to the current UTC time and returns its EPOCH and instant speed.

    Returns:
        dict: {
            "EPOCH": str,  # Closest matching EPOCH timestamp
            "instant speed": float  # Computed speed at the closest EPOCH
        }
    """
    # get the current UTC time in seconds
    now_time_in_seconds = time.mktime(time.gmtime())
    # place holder to track minimum time diff: 
    min_time_diff = float("inf")
    # EPOCH format
    value_format = '%Y-%jT%H:%M:%S.%fZ'
    
    # retreive all the EPOCH keys from redis DB:
    epoch_keys = rd.lrange('iss_keys', 0, -1)
    # in case the DB is empty:
    if not epoch_keys:
        return {'error': 'Database is empty.'}

    closest_epoch_key = None

    # iterate over all keys to find the closes time_value against curr_time_in_seconds
    for epoch_key in epoch_keys:
        # for each epoch key,  turn the time to seconds since Unix EPOCH
        dict_time_in_seconds = time.mktime(time.strptime(epoch_key.decode("utf-8"), value_format))
        # compute time difference compared to NOW:
        latest_time_diff = now_time_in_seconds - dict_time_in_seconds
        
        # figure out if the differene is the minimum.
        if abs(latest_time_diff) < min_time_diff:
            closest_epoch_key = epoch_key.decode("utf-8")
            min_time_diff = latest_time_diff
    
    now_speed = epoch_speed(closest_epoch_key)

    return now_speed
    
def compute_speed(x_velocity: float, y_velocity: float, z_velocity: float) -> float:
    """
    Computes the instantaneous speed given velocity components.

    Args:
        x_velocity (float): Velocity component along the X-axis (km/s).
        y_velocity (float): Velocity component along the Y-axis (km/s).
        z_velocity (float): Velocity component along the Z-axis (km/s).

    Returns:
        float: The computed speed in km/s.
    """
    return math.sqrt(x_velocity**2 + y_velocity**2 + z_velocity**2)


@app.route('/epochs/<epoch>/speed', methods=['GET'])
def epoch_speed(epoch:str)-> dict:
    """
    Computes the speed for a defined EPOCH.

    Args:
        epoch (str): The timestamp of the requested EPOCH.

    Returns:
        dict: {
            "EPOCH": str,  # The requested EPOCH timestamp
            "instant speed": float  # Computed speed at this EPOCH
        }
        If the EPOCH is not found, returns {'error': 'No matching EPOCH'}.
    """
    # get the state vector for that specific EPOCH
    state_vec = epoch_data(epoch)
    
    # check for any wrong EPOCH errors.
    if "error" in state_vec:
        return state_vec

    try: # let's try getting each velocity component
        x_dot = state_vec['X_DOT']['#text']
        y_dot = state_vec['Y_DOT']['#text']
        z_dot = state_vec['Z_DOT']['#text']
    except KeyError:
        return {'error':"Failed to extract velocity components, KeyError."}
    except TypeError:
        return {'error': "TypeError, failed to get velocity components."}

    # compute instant speed using existing compute_speed() func.
    instant_speed = compute_speed(float(x_dot), float(y_dot), float(z_dot))

    return {'EPOCH':epoch, 'instant speed':instant_speed}


def compute_location_astropy(sv: dict) -> tuple:
    """
    Converts the ISS state vector from GCRS (Geocentric Celestial Reference System)
    to ITRS (International Terrestrial Reference System) using Astropy.

    Args:
        sv (dict): The state vector containing position (X, Y, Z) and EPOCH.

    Returns:
        tuple: (latitude, longitude, altitude) of ISS in degrees and km.
        If an error occurs, returns {'error': '...'}.
    """
    # try accessing 3D coordinate elemnts:
    try:
        x = float(sv['X']['#text'])
        y = float(sv['Y']['#text'])
        z = float(sv['Z']['#text'])
    # handle any key errors, type errors or value errors
    except (KeyError, TypeError, ValueError) as e:
        print(f"Error extracting coordinates: {e}")
        return None, None, None
    
    # assumes epoch is in format '2024-067T08:28:00.000Z'
    try: # Convert EPOCH format from NASA's "%Y-%jT%H:%M:%S.%fZ" to "%Y-%m-%d %H:%M:%S.%f"
        this_epoch=time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(sv['EPOCH'][:-5], '%Y-%jT%H:%M:%S'))
    except ValueError as e:
        print(f"Error parsing EPOCH time: {e}")
        return None, None, None
    
    # Convert ISS position from GCRS to ITRS (Earth coordinates)
    cartrep = coordinates.CartesianRepresentation([x, y, z], unit=units.km)
    gcrs = coordinates.GCRS(cartrep, obstime=this_epoch)
    itrs = gcrs.transform_to(coordinates.ITRS(obstime=this_epoch))
    loc = coordinates.EarthLocation(*itrs.cartesian.xyz)

    return loc.lat.value, loc.lon.value, loc.height.value


def compute_nearest_geolocation(lat: float, lon: float) -> str:
    """
    Finds the nearest geographic location based on latitude and longitude.

    Args:
        lat (float): Latitude in degrees.
        lon (float): Longitude in degrees.

    Returns:
        str: <display name of nearest geolocation>
        If no location is found, returns 'No Nearest Geolocation Found. ISS might be hovering over an ocean.'
    """
    zoom_level = 15
    max_zoom_level = 18
    min_zoom_level = 10

    geocoder = Nominatim(user_agent='iss_tracker')
    geoloc = geocoder.reverse((lat, lon), zoom=zoom_level, language='en')
    
    # Try zooming out or zooming in:
    # First, try zooming in for better accuracy
    while zoom_level <= max_zoom_level and geoloc is None:
        zoom_level += 1
        geoloc = geocoder.reverse((lat, lon), zoom=zoom_level, language='en')
    
    zoom_level = 15
    # If still None, try zooming out to find a general area
    while zoom_level >= min_zoom_level and geoloc is None:
        zoom_level -= 1
        geoloc = geocoder.reverse((lat, lon), zoom=zoom_level, language='en')

    if geoloc is None:
        return f"No Nearest Geolocation Found. ISS might be hovering over an ocean."
    else:
        return geoloc.raw.get('display_name', 'Unknown Geolocation')


@app.route('/epochs/<epoch>/location', methods = ['GET'])
def epoch_location(epoch: str) -> dict:
    """
    Returns the ISS's location (latitude, longitude, altitude) and nearest geolocation for a given EPOCH.

    Args:
        epoch (str): The timestamp for the requested EPOCH.

    Returns:
        dict: {
            "latitude": float,    # Latitude in degrees
            "longitude": float,   # Longitude in degrees
            "altitude": float,    # Altitude in km
            "Nearest Geolocation": str  # The closest named location
        }
        If an error occurs, returns {'error': '...'}.
    """
    
    state_vec = epoch_data(epoch) # get the state vector for given EPOCH
    
    # get latitude, longitude, and altitude values
    lat, lon, alt = compute_location_astropy(state_vec)
    # check if the function returned any non-floating values:
    if lat == None:
        return {'error': 'Failed to Extract Latitude, Longitude, and Height.'}
    
    # get geolocation
    geolocation = compute_nearest_geolocation(lat, lon)
    
    return jsonify({'latitude':lat, 'longitude': lon, 'altitude':alt, 'Nearest Geolocation':geolocation})



if __name__ == "__main__":
    #main()
    app.run(debug=True, host="0.0.0.0")
