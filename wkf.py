from flask import Flask, request
import logging
import hashlib
import requests 
from requests.auth import HTTPBasicAuth
import base64
import html
from webdav4.client import Client
import xml.etree.ElementTree as ET
import random
import string
import os
import shutil
import datetime
import json
from flask_httpauth import HTTPBasicAuth as Flask_basic_auth

#https://skshetry.github.io/webdav4/reference/client.html#webdav4.client.Client.upload_file
#https://docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/basic.html
#https://docs.nextcloud.com/server/latest/developer_manual/client_apis/OCS/ocs-api-overview.html
#https://docs.nextcloud.com/server/latest/developer_manual/client_apis/OCS/ocs-status-api.html


app = Flask(__name__)
auth = Flask_basic_auth()

USERS = json.loads(os.environ.get('USERS'))

UTF8ENCODE = "utf-8"

TEMP_DIR = "./temp"

J2EEUSERNAME = os.environ.get('J2EEUSERNAME') 
J2EEPASSWORD = os.environ.get('J2EEPASSWORD') 
JIRIDEUSERNAME = os.environ.get('JIRIDEUSERNAME') 
JIRIDEPASSWORD = os.environ.get('JIRIDEPASSWORD') 

NEXTCLOUD_USERNAME = os.environ.get('NEXTCLOUD_USERNAME')
NEXTCLOUD_PASSWORD = os.environ.get('NEXTCLOUD_PASSWORD') 
NEXTCLOUD_SHARE_DIRECTORY = "shares"

NEXTCLOUD_WEBDAV_BASE_PATH = f"/{NEXTCLOUD_USERNAME}/{NEXTCLOUD_SHARE_DIRECTORY}"
NEXTCLOUD_SHARE_BASE_PATH = f"/{NEXTCLOUD_SHARE_DIRECTORY}" 
NEXTCLOUD_PUBLIC_LINK = 3
NEXTCLOUD_READ_PERMISSION = 1
NEXTCLOUD_SHARE_PASSWORD_LENGTH = 16
NEXTCLOUD_DEFAULT_PASSWORD_STATE = True

SAGA_BASE_URL = os.environ.get('SAGA_WS')
NEXTCLOUD_WEBDAV_BASE_URL = "https://cloud.provincia.lucca.it/remote.php/dav/files/"
NEXTCLOUD_SHARE_API_URL = "https://cloud.provincia.lucca.it/ocs/v2.php/apps/files_sharing/api/v1/shares"

docExtract = f"""<soapenv:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:RepWSSGateway">
   <soapenv:Header/>
   <soapenv:Body>
      <urn:docExtract soapenv:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
         <logonCredentials xsi:type="xsd:string"><![CDATA[
         		<logon_credentials
				j2eeusername="{J2EEUSERNAME}"
				j2eepassword="{J2EEPASSWORD}"
				username= "{JIRIDEUSERNAME}"
				password= "{JIRIDEPASSWORD}"
			/>
		]]></logonCredentials>
         <documentUID xsi:type="xsd:string">__DOCUMENT_ID__</documentUID>
      </urn:docExtract>
   </soapenv:Body>
</soapenv:Envelope>"""

docGetInfo = f"""<soapenv:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:RepWSSGateway">
   <soapenv:Header/>
   <soapenv:Body>
      <urn:docGetInfo soapenv:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
         <logonCredentials xsi:type="xsd:string"><![CDATA[
         		<logon_credentials
				j2eeusername="{J2EEUSERNAME}"
				j2eepassword="{J2EEPASSWORD}"
				username= "{JIRIDEUSERNAME}"
				password= "{JIRIDEPASSWORD}"
			/>
		]]></logonCredentials>
         <documentUID xsi:type="xsd:string">__DOCUMENT_ID__</documentUID>
      </urn:docGetInfo>
   </soapenv:Body>
</soapenv:Envelope>"""

logging.basicConfig(level=logging.DEBUG, format=f'%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

class MissingElement(Exception):
    pass

class GenericError(Exception):
    pass

@auth.verify_password
def verify_password(username, password):
    logger = logging.getLogger()

    logger.debug(f"username / password: {username}/{password}")
    if username in USERS:
        if USERS.get(username) == password:
            return username

@app.post("/share")
@auth.login_required
def share():
    # {
    # "documento_oggetto": "Descrizione del fascicolo",
    # "files_id": "123", 
    # OPZ "data_scadenza_share": "2023-05-31",
    # OPZ "usa_password" : "si"
    # }

    result = {}
    logger = logging.getLogger()

    try:
        now = datetime.datetime.now()
        
        #md5OggettoFascicolo = "" 
        xmlDocumentExtract = ""
        xmlDocumentInfo = ""
        #today = datetime.datetime.today()
        usaPassword = NEXTCLOUD_DEFAULT_PASSWORD_STATE
        shareUpdate = False
        NoneType = type(None)
        shareExpireRequestedDatetime = None
        shareExpireRequested = None
        #passwordSaga = ""
        nextCloudFolderId = None
        nextCloudUpdate = False
        nextcloud_webdav_directory_url = None

        md5String = hashlib.md5(now.strftime("%Y-%m-%dT%H:%M:%S%f %z").encode(UTF8ENCODE)).hexdigest()
        
        # Acquisisco i parametri di chiamata e preparo l'ambiente per l'elaborazione della chiamata
        logger.info("Acquisisco i parametri di chiamata")
        request_data = request.get_json()
        request_headers = request.headers
        logger.debug(f"Headers: {request_headers}")

        logger.debug(f"Parametri di chiamata {request_data}")
        
        
        if "files_id" in request_data:
            idDocumenti = request_data["files_id"]
            logger.debug(f"files_id {idDocumenti}")
            if (idDocumenti is None) or (type(idDocumenti) == NoneType):
                logger.error(f"files_id non impostato")
                raise MissingElement("files_id non impostato")
            if (len(idDocumenti) == 0):
                raise MissingElement("files_id vuoto")
        else:
            raise MissingElement("files_id mancante nella chiamata")
        
        if "share_id" in request_data:
            nextCloudFolderId = request_data["share_id"]
            if (nextCloudFolderId is not None) and (type(nextCloudFolderId) != NoneType):
                #E' un aggiornamento di una cartella già presente 
                nextCloudUpdate = True
                logger.info (f"share_id parameter value: {nextCloudFolderId}")

        if (nextCloudUpdate == False):
            if "documento_oggetto" in request_data:
                oggettoFascicolo = request_data["documento_oggetto"]
                logger.debug(f"documento_oggetto del fascicolo : {oggettoFascicolo}")
                if (oggettoFascicolo is None) or (type(oggettoFascicolo) == NoneType):
                    logger.error(f"documento_oggetto non impostato")
                    raise MissingElement("documento_oggetto non impostato")
                if (len(oggettoFascicolo) == 0):
                    raise MissingElement("documento_oggetto vuoto")
            else:
                raise MissingElement("documento_oggetto mancante nella chiamata")
            
            if "usa_password" in request_data:
                usaPasswordString = request_data["usa_password"]
                if (usaPasswordString is not None) and (type(usaPasswordString) != NoneType):
                    usaPassword = usaPasswordString.lower() not in ['false', '0', 'no']
                    logger.debug(f"Parametro usa_password {usaPasswordString}")
                else:
                 logger.info (f"Parametro usa_password non definito assumo il valore di default ({NEXTCLOUD_DEFAULT_PASSWORD_STATE})")
            else:
                logger.info (f"Parametro usa_password mancante assumo il valore di default ({NEXTCLOUD_DEFAULT_PASSWORD_STATE})")   

            if "data_scadenza_share" in request_data:
                shareExpireRequested = request_data["data_scadenza_share"]
                if (shareExpireRequested is not None) and (type(shareExpireRequested) != NoneType):
                    if (shareExpireRequested != ''):
                        shareExpireRequestedDatetime = datetime.datetime.strptime(shareExpireRequested, '%Y-%m-%d')
                        logger.debug(f"Termine condivisione {shareExpireRequested}")
            else:
                logger.info (f"Parametro data_scadenza_share mancante, nessuna scadenza della share")

        # Preparo l'ambiente per l'elaborazione della chiamata
        logger.debug(f"Preparo l'ambiente per l'elaborazione della chiamata")
        client = Client(NEXTCLOUD_WEBDAV_BASE_URL, auth=(NEXTCLOUD_USERNAME, NEXTCLOUD_PASSWORD))

        # Nextcloud
        if (nextCloudUpdate):
            # Se è un aggiornamento, inizio svuotando la cartella fornita
            logger.info("Checking content of submitted nextCloudFolderId...")
            nextcloud_webdav_directory_url = NEXTCLOUD_WEBDAV_BASE_PATH + "/" + nextCloudFolderId  
            logger.debug(f"nextcloud_webdav_directory_url :{nextcloud_webdav_directory_url}")
        
            if (client.exists(nextcloud_webdav_directory_url)):
                logger.debug(f"Trashing old shared directory content on Nextcloud")
                nextcloudFiles = client.ls(nextcloud_webdav_directory_url)
                logger.debug(f"Folder content: {nextcloudFiles}")

                for nextcloudFile in nextcloudFiles:
                    logger.debug(f"Deleting file {nextcloudFile['name']}")
                    nextcloud_webdav_directory_file_url = nextcloudFile['name']
                    client.remove(nextcloud_webdav_directory_file_url)
                
            else:
                raise GenericError("Submitted nextCloudFolderId does not exists")
        else:
            # Creo su Nextcloud la cartella
            nextCloudFolderId = md5String

            logger.info(f"Creating Nextcloud folder ({nextCloudFolderId})")
            nextcloud_webdav_directory_url = NEXTCLOUD_WEBDAV_BASE_PATH + "/" + nextCloudFolderId           
            logger.debug(f"nextcloud_webdav_directory_url :{nextcloud_webdav_directory_url}")
            client.mkdir(nextcloud_webdav_directory_url)

        # Creo la directory sul file system
        logger.debug(f"Creazione directory {md5String} su file system...")
        instanceDir = os.path.join(os.getcwd(), TEMP_DIR, md5String)
        os.makedirs(instanceDir)

        # Elaboro i documenti che devo caricare
        for idDocumento in idDocumenti:
            now = datetime.datetime.now()

            xmlDocumentExtract = docExtract.replace("__DOCUMENT_ID__", str(idDocumento))
            xmlDocumentInfo = docGetInfo.replace("__DOCUMENT_ID__", str(idDocumento))
            logger.debug("Nextcloud document id related xml :" + xmlDocumentExtract)

            # Acquisisco informazioni sul file da SAGA
            logger.info("Getting info on document_id from SAGA")
            request_result = requests.post(SAGA_BASE_URL, data=xmlDocumentInfo, headers={'content-type': 'text/xml', 'SOAPAction' : ''})
            logger.debug(f"Saga document info (html encoded) result: {request_result.text}")

            tree = ET.fromstring(request_result.content)
            documentInfo = (tree.find('.//docGetInfoReturn').text)
            documentInfoDecoded = html.unescape(documentInfo)
            logger.debug(f"Document info unescaped: {documentInfoDecoded}")

            tree = ET.fromstring(documentInfoDecoded)
            sagaDocumentNameMd5 = hashlib.md5(now.strftime("%Y-%m-%dT%H:%M:%S:%f %z").encode(UTF8ENCODE)).hexdigest()
            sagaDocumentName = sagaDocumentNameMd5 + "-" + tree.attrib["document_name"]
            sagaDocumentNameWithDirectory = os.path.join(instanceDir, sagaDocumentName)
            logger.debug(f"Saga document name : {sagaDocumentName}")
            #print(ET.tostring(tree, encoding='unicode'))

            # Acquisisco il documento da SAGA
            logger.info("Getting document from SAGA")
            request_result = requests.post(SAGA_BASE_URL, data=xmlDocumentExtract, headers={'content-type': 'text/xml', 'SOAPAction' : ''})
            #logger.debug(f"Saga document extract result: {request_result.text}")

            tree = ET.fromstring(request_result.content)
            sagaDocumentFaultString = tree.find('.//faultstring')
            if (sagaDocumentFaultString) is not None:
                logger.error(f"Saga document faultstring : {sagaDocumentFaultString.text}")
                raise GenericError(sagaDocumentFaultString.text)

            sagaDocument = tree.find('.//docExtractReturn').text
            sagaDocumentDecoded = base64.b64decode(sagaDocument)

            # Scrivo il documento sul file system
            logger.info("Writing document to file system")
            with open(sagaDocumentNameWithDirectory, 'wb') as output_file:
                output_file.write(sagaDocumentDecoded)

            # Carico il documento su NEXTCLOUD
            logger.info("Loading file to Nextcloud")
            nextcloud_file_url = f"{nextcloud_webdav_directory_url}/{sagaDocumentName}" 
            logger.debug(f"Loading file to {nextcloud_file_url}")
            client.upload_file(sagaDocumentNameWithDirectory, nextcloud_file_url)

        if (nextCloudUpdate == False):
            # Genero la condivisione
            logger.info("Creating share...")
            sharePassword = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(NEXTCLOUD_SHARE_PASSWORD_LENGTH))
        
            nextcloud_share_directory_url = NEXTCLOUD_SHARE_BASE_PATH + "/" + md5String 

            payload = {
                'path': nextcloud_share_directory_url,
                'shareType': NEXTCLOUD_PUBLIC_LINK,
                'publicUpload':'yes',
                'permissions' : NEXTCLOUD_READ_PERMISSION,
                'note' : oggettoFascicolo
            }

            if (usaPassword):
                payload["password"] = sharePassword
                payload["publicUpload"] = 'false'
                
            if (shareExpireRequestedDatetime != None):
                payload["expireDate"] = shareExpireRequestedDatetime.strftime('%Y-%m-%d')

            logger.debug(f"Payload share call : {payload}")
            request_result = requests.post(NEXTCLOUD_SHARE_API_URL,data = payload, auth=HTTPBasicAuth(NEXTCLOUD_USERNAME, NEXTCLOUD_PASSWORD), headers={'content-type': 'application/x-www-form-urlencoded', 'OCS-APIRequest' : 'true'})
            logger.debug(f"Nextcloud share result: {request_result.text}")

            # Acquisisco le informazioni di condivisione
            logger.info("Getting share operation result...")
            tree = ET.fromstring(request_result.content)

            operationResult = tree.find('.//meta/status').text
            logger.info(f"Share operation result: {operationResult}")
            if (operationResult == "ok"):
                shareTokenNextcloud = tree.find('.//token').text
                ##shareTokenNextcloud = "8tg6pEbEy6Z9HL7"
                shareTokenUrl = tree.find('.//url').text
                ##shareTokenUrl = "https://cloud.provincia.lucca.it/s/8tg6pEbEy6Z9HL7"
                shareTokenStatus = tree.find('.//status').text
                ##shareTokenStatus = "ok"
                shareTokenMessage = tree.find('.//message').text
                ##shareTokenMessage = "Condivisione creata correttamente"
                    
                result['status'] = "ok"
                result['url'] = shareTokenUrl
                result['data_scadenza_share'] = shareExpireRequested
                result['message'] = "Data published successfully"

                if (usaPassword):
                    result['password'] = sharePassword

                result['share_id'] = nextCloudFolderId
            else:
                result['status'] = operationResult
                result['message'] = tree.find('.//meta/message').text
            
        else:
            result['status'] = "ok"
            result['message'] = "Folder updated"

            result['share_id'] = nextCloudFolderId

        # Ripulisco l'ambiente rispetto all'istanza appena eseguita
        logger.info(f"Deleting temporary data on file system")
        shutil.rmtree(instanceDir)
            
    except Exception as error:
        logger.error(f"Error : {repr(error)}")
        result['status'] = "error"
        result['message'] = repr(error)
     
    logger.debug(f"Result : {result}")
    return result

if __name__ == "__main__":
    logger = logging.getLogger()
    logger.debug(f"Using J2EEUSERNAME({J2EEUSERNAME}), J2EEPASSWORD({J2EEPASSWORD}), JIRIDEUSERNAME({JIRIDEUSERNAME}), JIRIDEUSERNAME({JIRIDEPASSWORD}), NEXTCLOUD_USERNAME({NEXTCLOUD_USERNAME}), NEXTCLOUD_PASSWORD ({NEXTCLOUD_PASSWORD}), USERS({USERS})")

    #app.run(ssl_context=('tls.crt','tls.key'), host='0.0.0.0')
    app.run(host='0.0.0.0')






