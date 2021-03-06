from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import TokenExpiredError
import requests
import re
import json
import pickle
import os
import logging
import urllib
from pickle import UnpicklingError

client_id = '79742319e39245de5f91d15ff4cac2a8';
client_secret = '8ad97aceb92c5892e102b093c7c083fa';
authorizeURL = 'https://iam.viessmann.com/idp/v1/authorize';
token_url = 'https://iam.viessmann.com/idp/v1/token';
apiURLBase = 'https://api.viessmann-platform.io';
redirect_uri = "vicare://oauth-callback/everest";
viessmann_scope=["openid"]
logger = logging.getLogger('ViCare')
logger.addHandler(logging.NullHandler())

# TODO Holiday program can still be used (parameters are there) heating.circuits." + str(self.circuit) + ".operating.programs.holiday
# TODO heating.dhw.schedule/setSchedule
# TODO handle multi install / multi devices

""""Viessmann ViCare API Python tools"""

class ViCareSession:
    """This class connects to the Viesmann ViCare API.
    The authentication is done through OAuth2.
    Note that currently, a new token is generate for each run.
    """


    def __init__(self, username, password,token_file=None,circuit=0):
        """Init function. Create the necessary oAuth2 sessions
        Parameters
        ----------
        username : str
            e-mail address
        password : str
            password

        Returns
        -------
        """

        self.username= username
        self.password= password
        self.token_file=token_file
        self.circuit=circuit
        self.oauth=self.__restoreToken(token_file)
        self._getInstallations()
        logger.info("Initialisation successful !")

    def __restoreToken(self,token_file=None):
        """Create the necessary oAuth2 sessions
        Restore it from token_file if existing (token dict)
        Viessmann tokens expire after 3600s (60min)
        Parameters
        ----------
        username : str
            e-mail address
        password : str
            password
        token_file: str
            path to serialize the token (will restore if already existing)

        Returns
        -------
        oauth:
            oauth sessions object
        """
        if (token_file!=None) and os.path.isfile(token_file):
            try:
                logger.info("Token file exists")
                oauth = OAuth2Session(client_id,token=self._deserializeToken(token_file))
                logger.info("Token restored from file")
            except UnpicklingError:
                logger.warning("Could not restore token")
                oauth = self.__getNewToken(self.username, self.password,token_file)
        else:
            logger.debug("Token file argument not provided or file does not exist")
            oauth = self.__getNewToken(self.username, self.password,token_file)
        return oauth

    def __getNewToken(self, username, password,token_file=None):
        """Create a new oAuth2 sessions
        Viessmann tokens expire after 3600s (60min)
        Parameters
        ----------
        username : str
            e-mail address
        password : str
            password
        token_file: str
            path to serialize the token (will restore if already existing). No serialisation if not present

        Returns
        -------
        oauth:
            oauth sessions object
        """
        oauth = OAuth2Session(client_id, redirect_uri=redirect_uri,scope=viessmann_scope)
        authorization_url, state = oauth.authorization_url(authorizeURL)
        codestring=""
        logger.debug("Auth URL is: "+authorization_url)

        try:
            header = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = requests.post(authorization_url, headers=header,auth=(username,password))
            logger.warning("Reeived an HTML answer from the server during auth, this is not normal:")
            logger.debug(response.content)
        except requests.exceptions.InvalidSchema as e:
            #capture the error, which contains the code the authorization code and put this in to codestring
            codestring = "{0}".format(str(e.args[0])).encode("utf-8");
            codestring = str(codestring)
            match = re.search("code\=(.*)\&",codestring)
            codestring=match.group(1)
            logger.debug("Codestring : "+codestring)
            oauth.fetch_token(token_url, client_secret=client_secret,authorization_response=authorization_url,code=codestring)
            logger.debug("Token received: ")
            logger.debug(oauth)
            logger.debug("Start serial")
            if token_file != None:
                self._serializeToken(oauth.token,token_file)
                logger.info("Token serialized to "+token_file)
            logger.info("New token created")
            #TODO throw an exception if oauth is null and implement the auth required method
            return oauth

        # TODO tranform to exception
        
    def renewToken(self):
        logger.warning("Token expired, renewing")
        self.oauth=self.__getNewToken(self.username,self.password,self.token_file)
        logger.info("Token renewed successfully")
            
        
    """Get URL using OAuth session. Automatically renew the token if needed
    Parameters
    ----------
    url : str
        URL to get

    Returns
    -------
    result: json
        json representation of the answer
    """
    def __get(self,url):
        try:
            #if(self.oauth==None):
            #    self.renewToken()
            r=self.oauth.get(url).json()
            logger.debug("Response to get request: "+str(r))
            if(r=={'error': 'EXPIRED TOKEN'}):
                logger.warning("Abnormal token, renewing") # apparently forged tokens TODO investigate
                self.renewToken()
                r = self.oauth.get(url).json()
            return r
        except TokenExpiredError as e:
            self.renewToken()
            return self.__get(url)


    """POST URL using OAuth session. Automatically renew the token if needed
    Parameters
    ----------
    url : str
        URL to get
    data : str
        Data to post

    Returns
    -------
    result: json
        json representation of the answer
    """
    def __post(self,url,data):
        h = {"Content-Type":"application/json","Accept":"application/vnd.siren+json"}
        try:
            #if(self.oauth==None):
            #    self.renewToken()
            j=self.oauth.post(url,data,headers=h)
            try:
                r=j.json()
                return r
            except json.decoder.JSONDecodeError:
                if j.status_code == 204:
                    return json.loads("{\"statusCode\": 204, \"error\": \"None\", \"message\": \"SUCCESS\"}")
                else:
                    return json.loads("{\"statusCode\":"+j.status_code+", \"error\": \"Unknown\", \"message\": \"UNKNOWN\"}")
        except TokenExpiredError as e:
            self.renewToken()
            return self._post(url,data)

    def _serializeToken(self,oauth,token_file):
        binary_file = open(token_file,mode='wb')
        s_token = pickle.dump(oauth,binary_file)
        binary_file.close()

    def _deserializeToken(self,token_file):
        binary_file = open(token_file,mode='rb')
        s_token = pickle.load(binary_file)
        return s_token

    def _getInstallations(self):
        self.installations = self.__get(apiURLBase+"/general-management/installations?expanded=true&")
        #logger.debug("Installations: "+str(self.installations))
        #self.href=self.installations["entities"][0]["links"][0]["href"]
        self.id=self.installations["entities"][0]["properties"]["id"]
        self.serial=self.installations["entities"][0]["entities"][0]["properties"]["serial"]
        return self.installations

    def getInstallations(self):
        return self.installations

    def getProperty(self,property_name):
        url = apiURLBase + '/operational-data/installations/' + str(self.id) + '/gateways/' + str(self.serial) + '/devices/0/features/' + property_name
        j=self.__get(url)
        return j

    def setProperty(self,property_name,action,data):
        url = apiURLBase + '/operational-data/v1/installations/' + str(self.id) + '/gateways/' + str(self.serial) + '/devices/0/features/' + property_name +"/"+action
        return self.__post(url,data)
    """ Set the active mode
    Parameters
    ----------
    mode : str
        Valid mode can be obtained using getModes()

    Returns
    -------
    result: json
        json representation of the answer
    """
    def setMode(self,mode):
        r=self.setProperty("heating.circuits." + str(self.circuit) + ".operating.modes.active","setMode","{\"mode\":\""+mode+"\"}")
        return r

    # Works for normal, reduced, comfort
    # active has no action
    # exetenral , standby no action
    # holiday, sheculde and unscheduled
    # activate, decativate comfort,eco
    """ Set the target temperature for the target program
    Parameters
    ----------
    program : str
        Can be normal, reduced or comfort
    temperature: int
        target temperature

    Returns
    -------
    result: json
        json representation of the answer
    """
    def setProgramTemperature(self,program: str,temperature :int):
        return self.setProperty("heating.circuits." + str(self.circuit) + ".operating.programs."+program,"setTemperature","{\"targetTemperature\":"+str(temperature)+"}")

    def setReducedTemperature(self,temperature):
        return self.setProgramTemperature("reduced",temperature)

    def setComfortTemperature(self,temperature):
        return self.setProgramTemperature("comfort",temperature)

    def setNormalTemperature(self,temperature):
        return self.setProgramTemperature("normal",temperature)

    """ Activate a program
        NOTE
        DEVICE_COMMUNICATION_ERROR can just mean that the program is already on
    Parameters
    ----------
    program : str
        Appears to work only for comfort

    Returns
    -------
    result: json
        json representation of the answer
    """
    # optional temperature parameter could be passed (but not done)
    def activateProgram(self,program):
        return self.setProperty("heating.circuits." + str(self.circuit) + ".operating.programs."+program,"activate","{}")

    def activateComfort(self):
        return self.activateProgram("comfort")
    """ Deactivate a program
    Parameters
    ----------
    program : str
        Appears to work only for comfort and eco (coming from normal, can be reached only by deactivating another state)

    Returns
    -------
    result: json
        json representation of the answer
    """
    def deactivateProgram(self,program):
        return self.setProperty("heating.circuits." + str(self.circuit) + ".operating.programs."+program,"deactivate","{}")
    def deactivateComfort(self):
        return self.deactivateProgram("comfort")

    """ Set the target temperature for domestic host water
    Parameters
    ----------
    temperature : int
        Target temperature

    Returns
    -------
    result: json
        json representation of the answer
    """
    def setDomesticHotWaterTemperature(self,temperature):
        return self.setProperty("heating.dhw.temperature","setTargetTemperature","{\"temperature\":"+str(temperature)+"}")

    def getMonthSinceLastService(self):
        try:
            return self.getProperty("heating.service.timeBased")["properties"]["activeMonthSinceLastService"]["value"]
        except KeyError:
            return "error"

    def getLastServiceDate(self):
        try:
            return self.getProperty("heating.service.timeBased")["properties"]["lastService"]["value"]
        except KeyError:
            return "error"

    def getOutsideTemperature(self):
        try:
            return self.getProperty("heating.sensors.temperature.outside")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getSupplyTemperature(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".sensors.temperature.supply")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getRoomTemperature(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".sensors.temperature.room")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getModes(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.modes.active")["actions"][0]["fields"][0]["enum"]
        except KeyError:
            return "error"

    def getActiveMode(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.modes.active")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getHeatingCurveShift(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".heating.curve")["properties"]["shift"]["value"]
        except KeyError:
            return "error"

    def getHeatingCurveSlope(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".heating.curve")["properties"]["slope"]["value"]
        except KeyError:
            return "error"

    def getBoilerTemperature(self):
        try:
            return self.getProperty("heating.boiler.sensors.temperature.main")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getActiveProgram(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.programs.active")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getPrograms(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.programs")["entities"][9]["properties"]["components"]
        except KeyError:
            return "error"

    def getDesiredTemperatureForProgram(self , program):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.programs."+program)["properties"]["temperature"]["value"]
        except KeyError:
            return "error"

    def getCurrentDesiredTemperature(self):
        try:
            return self.getProperty("heating.circuits." + str(self.circuit) + ".operating.programs."+self.getActiveProgram())["properties"]["temperature"]["value"]
        except KeyError:
            return "error"

    def getDomesticHotWaterConfiguredTemperature(self):
        try:
            return self.getProperty("heating.dhw.temperature")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getDomesticHotWaterStorageTemperature(self):
        try:
            return self.getProperty("heating.dhw.sensors.temperature.hotWaterStorage")["properties"]["value"]["value"]
        except KeyError:
            return "error"

    def getDomesticHotWaterMaxTemperature(self):
        try:
            return self.getProperty("heating.dhw.temperature")["actions"][0]["fields"][0]["max"]
        except KeyError:
            return "error"

    def getDomesticHotWaterMinTemperature(self):
        try:
            return self.getProperty("heating.dhw.temperature")["actions"][0]["fields"][0]["min"]
        except KeyError:
            return "error"

    def getGasConsumptionHeatingDays(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['day']['value']
        except KeyError:
            return "error"

    def getGasConsumptionHeatingToday(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['day']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionHeatingWeeks(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['week']['value']
        except KeyError:
            return "error"

    def getGasConsumptionHeatingThisWeek(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['week']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionHeatingMonths(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['month']['value']
        except KeyError:
            return "error"

    def getGasConsumptionHeatingThisMonth(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['month']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionHeatingYears(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['year']['value']
        except KeyError:
            return "error"

    def getGasConsumptionHeatingThisYear(self):
        try:
            return self.getProperty('heating.gas.consumption.heating')['properties']['year']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterDays(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['day']['value']
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterToday(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['day']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterWeeks(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['week']['value']
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterThisWeek(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['week']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterMonths(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['month']['value']
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterThisMonth(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['month']['value'][0]
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterYears(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['year']['value']
        except KeyError:
            return "error"

    def getGasConsumptionDomesticHotWaterThisYear(self):
        try:
            return self.getProperty('heating.gas.consumption.dhw')['properties']['year']['value'][0]
        except KeyError:
            return "error"

    def getCurrentPower(self):
        try:
            return self.getProperty('heating.burner.current.power')['properties']['value']['value']
        except KeyError:
            return "error"

    def getBurnerActive(self):
        try:
            return self.getProperty("heating.burner")["properties"]["active"]["value"]
        except KeyError:
            return "error"

