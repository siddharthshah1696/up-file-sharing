from flask import Flask, request
from flask_restful import Api, Resource, reqparse
from flask import jsonify
import base64
import json
import os
import boto3, botocore
from sqlPy import *

S3_BUCKET                 = "up-bucket-brogrammers"
S3_LOCATION               = 'https://s3.ap-south-1.amazonaws.com/up-bucket-brogrammers/'
USE_MYSQL_DB = 1

app = Flask(__name__)
api = Api(app)

pendingFileTable = {}
#format- {receiver : [(sender, filename)]}
#list of tuples - so that if we have multiple files for single receiver

def getEntryFromPendingTable(username, type=0):
	global pendingFileTable
	if USE_MYSQL_DB == 0:
		result = pendingFileTable.get(username)
		return result
	else:
		DBresult = queryFilePending(username)
		if type == 0:
			result = list((i[0], i[1]) for i in DBresult)
		elif type == 1:				# with timestamp and filesize
			result = list((i[0], i[1], i[3], i[4]) for i in DBresult)
		return result

def putEntryIntoPendingTable(receiver, sender, filename, filesize="N/A", filehash="N/A"):
	#print(10)
	global pendingFileTable
	if USE_MYSQL_DB == 0:
		if getEntryFromPendingTable(receiver):
			pendingFileTable[receiver].append((sender, filename))
		else:
			pendingFileTable[receiver] = [(sender, filename)]
		return True
	else:
		return insertFilePending(sender, receiver, filename, filehash, filesize)
		
def removeEntryFromPendingTable(receiver, sender, filename):
	global pendingFileTable
	if USE_MYSQL_DB == 0:
		pendingFileTable[receiver].remove((sender, filename))
		return True
	else:
		return deleteFilePending(receiver, sender, filename)	

def upload_file_to_s3(file, bucket_name):
	# Replace S3_BUCKET with parameter bucket_name
	s3 = boto3.client('s3')
	try:
		s3.upload_file("UserFiles/"+file, S3_BUCKET, file)

	except Exception as e:
		print("Something bad happened during upload : FN = " + file + "; " + str(e))
		return e

	return "{}{}".format(S3_LOCATION, file)

def download_file_from_s3(file, bucket_name):
	# Replace S3_BUCKET with parameter bucket_name

	s3 = boto3.client('s3')
	# Download object at bucket-name with key-name to file-like object
	try:
		s3.download_file(S3_BUCKET, file, "UserFiles/"+"s3_"+file)

	except Exception as e:
		print("Something bad happened during download : FN = " + file + "; " + str(e))
		return e

	return "File downloaded"

def delete_file_from_s3(file, bucket_name):
	# Replace S3_BUCKET with parameter bucket_name
	s3 = boto3.resource('s3')
	try:
		s3.Object(S3_BUCKET, file).delete()

	except Exception as e:
		print("Something bad happened during delete : FN = " + file + "; " + str(e))
		return e

	return "File deleted!"
	

class FilePending(Resource):
	#@app.route('/fp/<string:name>', methods=['GET'])
	def get(self, name):
		
		pendingList = getEntryFromPendingTable(name, 1)
		#implement a check here against impersonation
		if pendingList:
			return jsonify(pendingList)
		else:
			return "0", 404
	#@app.route('/fp', methods=['POST'])
	def post(self):
		return "Invalid", 404

	#@app.route('/fp', methods=['PUT'])
	def put(self):
		return "Invalid", 404	

	#@app.route('/fp', methods=['DELETE'])
	def delete(self):
		return "Invalid", 404
#after this API, all senders and filename info will be with client
		
class FileTransfer(Resource):
	#@app.route('/ft/<string:name>/<string:sender>/<string:filename>', methods=['GET'])
	def get(self, name, sender, filename):
		#request arguments - name, sender and filename
		
		#get the file. name = file name
		#implement check against impersonation

		# Sometimes filename may be erronous, when a question mark occurs in the file, or a special character
		# which the encoding couldn't process
		try:
			print(request.url)
			filename2 = request.url.split('/')[-1]
			if filename != filename2:
				print("Filename encoding issue, fixing " + filename + " to " + filename2)
				filename = filename2
		except Exception as e:
			print("Prob - " + str(e))
		pendingList = getEntryFromPendingTable(name)
		
		if pendingList and (sender, filename) in pendingList:
			download_file_from_s3(filename, S3_BUCKET)
			with open("UserFiles/"+"s3_"+filename, "r") as f:
				dataB64 = f.read()
			os.remove("UserFiles/"+"s3_"+filename)
			return dataB64, 200
		else:
			return "Not found", 404

	#@app.route('/ft', methods=['POST'])
	def post(self):
		# not in use, use PUT
		return "Use PUT", 404
		
	#@app.route('/ft', methods=['PUT'])
	def put(self):	
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"

			name = args["name"]
			receiver = args["sendto"]
			receivers = list(set(receiver.split(",")))
			filename = args["filename"]
			dataEncoded = args["data"]
			filesize = args.get("filesize")
			if not filesize:
				filesize = int(len(dataEncoded) * 0.75)	#approx	
			print("Filesize is " + str(filesize))	
			#not decoding b64 in server, do it in clientside
			with open("UserFiles/"+filename, "w") as g:
				g.write(dataEncoded)
				g.close()
			output = upload_file_to_s3(filename,S3_BUCKET)
			
			for receiver in receivers:
				receiver = receiver.strip()
				if not putEntryIntoPendingTable(receiver, name, filename, filesize):
					return "DB prob, maybe file name issue?", 400
						
			os.remove("UserFiles/"+filename)
			return "File uploaded at "+output, 200

		except Exception as e:
			print("File transfer request Exception" + str(e))			
			return e, 404

	#@app.route('/ft', methods=['DELETE'])
	def delete(self):
		#send an explicit delete request when file received
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"

			name = args["name"]
			sender = args["sender"]
			filename = args["filename"]
			pendingList = getEntryFromPendingTable(name)
			if pendingList and removeEntryFromPendingTable(name, sender, filename):			
				return "File deleted", 200
			else:
				return "File not found", 404
		except:
			return "File deletion exception", 404


class UserManager(Resource):

	def get(self):
		return "Use PUT/POST", 400

	def post(self, type):
		if type == "login":	
			try:
				args = request.get_json(force=True)
				if args == None:
					raise "JsonError"
				username = args["username"]
				password = args["password"]
				if verifyUser(username,password):
					return "Verified"
				else:
					return "Invalid credentials",404
			except:
				return "User Verification exception", 404

		elif type == "register":
			try:
				args = request.get_json(force=True)
				print(args)
				if args == None:
					raise "JsonError"
				username = args["username"]
				email = args["email"]

				number = args["number"]
				password = args["password"]
				name = args["name"]
				# Checking if username already in use
				result = queryUser(username)
				print("result is " + str(result))
				if result is False :
					insertUser(username, email, number, password, name)
					return "User Created", 200
				else:
					print("Should return already in use")
					return "Username already in use",404
			except Exception as e:
				print(str(e))				
				return "User Creation exception", 400

		elif type == "check":
			try:
				args = request.get_json(force=True)
				if args == None:
					raise "JsonError"
				print(args)
				usernames = list(set(args["username"].split(',')))
				invalid_users = ""
				for username in usernames:
					username=username.strip()
					if not queryUser(username):
						invalid_users+=username+" , "
					else:
						print(username+" verified")
				if len(invalid_users) == 0:
					return "User exists",200 
				else:
					# To remove last comma from string
					return "Invalid usernames: " + invalid_users[:-3],404
			except:
				return "User Exists Verification exception", 404

		else:
			return "Use login/register/check after um", 400

	def put(self):
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"
			username = args["username"]
			if queryUser(username):
				return jsonify( getUserHistory(username) ) 
			else:
				return "Invalid username",404
		except:
			return "User History Retrieval exception",404
		

	def delete(self):
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"
			username = args["username"]
			if deleteUser(username):
				# When we delete an account, we remove all pairings associated with it
				if deleteAllPairing(username):
					return username + " account and all its associated pairings deleted"
				else:
					return username + " account deleted but its associated pairings not deleted"
			else:
				return username + " account deletion failed",404
		except:
			return "User deletion exception", 404

class PairingManager(Resource):

	def get(self):
		return "Use POST/PUT",404

	def post(self,type):
		if type == "startPairing":
			try:
				args = request.get_json(force=True)
				if args == None:
					raise "JsonError"
				sender = args["sender"]
				receiver = args["receiver"]
				# Assuming that we don't have to ask sender for permission when receiver
				# sends pairing request
				# Checking if sender and receiver accounts are active(not been deleted)
				if queryUser(sender) == False:
					return "Pairing Error : "+sender+" username is invalid",404
				if queryUser(receiver) == False:
					return "Pairing Error : "+receiver+" username is invalid",404
				#Checking if pairing already exists
				if verifyPairing(sender,receiver):
					return "Pairing already exists",404
				# Initiate Pairing
				if insertPairRequest(sender,receiver):
					return "Pairing Completed"
			except:
				return "Pairing creation exception", 404

		elif type == "getPairs":
			try:
				args = request.get_json(force=True)
				if args == None:
					raise "JsonError"
				receiver = args["receiver"]
				# Checking if receiver account is active(not been deleted)			
				if queryUser(receiver) == False:
					return "Get Pairs Error : "+receiver+" username is invalid",404
				pairs = getPairsRequest(receiver)
				return jsonify(pairs)
			except:
				return "Get Pairs exception", 404	
		
		elif type == "removePairing":
			try:
				args = request.get_json(force=True)
				if args == None:
					raise "JsonError"
				sender = args["sender"]
				receiver = args["receiver"]
				
				# Checking if sender and receiver accounts are active(not been deleted)
				if queryUser(sender) == False:
					return "Remove Pairing Error : "+sender+" username is invalid",404
				if queryUser(receiver) == False:
					return "Remove Pairing Error : "+receiver+" username is invalid",404

				#Checking if pairing already exists
				if not verifyPairing(sender,receiver):
					return "Pairing already deleted",404

				# Initiate Pairing
				if deletePairRequest(sender,receiver):
					return "Pairing Deleted",404
			except:
				return "Pairing deletion exception", 404

	def put(self):
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"
			sender = args["sender"]
			receiver = args["receiver"]
			# Checking if sender and receiver accounts are active(not been deleted)
			if queryUser(sender) == False:
				return "Check Pairing Error : "+sender+" username is invalid",404
			if queryUser(receiver) == False:
				return "Check Pairing Error : "+receiver+" username is invalid",404
			if verifyPairing(sender,receiver):
				return "Paired"
			else:
				return "Not Paired",404
		except:
			return "Pairing Verification exception", 404

	def delete(self):
		try:
			args = request.get_json(force=True)
			if args == None:
				raise "JsonError"
			sender = args["sender"]
			receiver = args["receiver"]
			if deletePairing(sender,receiver) and deletePairing(receiver,sender):
				return "Pairing removed"
			else:
				return "Error in pairing removal",404
		except:
			return "Pairing Removal exception", 404

@app.route('/api/')
def index():
	return "Hello world! S3 and DB have been integrated !\nRegistration and Pairing Functionality has been added\n\rBrogrammers send their regards. :)	"

api.add_resource(FileTransfer, "/api/ft", '/api/ft/<string:name>/<string:sender>/<string:filename>')
api.add_resource(FilePending, "/api/fp", "/api/fp/<string:name>")
api.add_resource(UserManager, "/api/um", "/api/um/<string:type>")#/<string:email>/<string:number>/<string:password>/<string:name>")
api.add_resource(PairingManager, "/api/pm", "/api/pm/<string:type>")
if __name__ == "__main__": 
	app.run(debug=True)
