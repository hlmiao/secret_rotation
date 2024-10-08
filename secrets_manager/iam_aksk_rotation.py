import json
import boto3
import os

iam = boto3.client('iam')
secretsmanager = boto3.client('secretsmanager')

def lambda_handler(event, context):
    
    vsecret = os.getenv('secrets')
    secret_list = vsecret.split(';')

    for secret in secret_list:
        get_secret = secretsmanager.get_secret_value(SecretId=secret)
        secret_details = json.loads(get_secret['SecretString'])

        print("For user - " + secret_details['UserName'] + ", Access & Secret keys will be deleted.")
        
        # Extracting the key details from IAM
        key_response = iam.list_access_keys(UserName=secret_details['UserName'])
        
        # Existing Key Deletion
        for key in key_response['AccessKeyMetadata']:
            iam.delete_access_key(UserName=secret_details['UserName'], AccessKeyId=key['AccessKeyId'])
            print(key['AccessKeyId'] + " key of " + secret_details['UserName'] + " has been deleted.")
        
        # New Key Creation
        create_response = iam.create_access_key(UserName=secret_details['UserName'])
        print("A new set of keys has been created for user - " + secret_details['UserName'])
        
        # Updating the secret value
        NewSecret = '{"UserName":"' + create_response['AccessKey']['UserName'] + '", "AccessKeyId":"' + create_response['AccessKey']['AccessKeyId'] + '", "SecretAccessKey":"' + create_response['AccessKey']['SecretAccessKey'] + '"}'
        secretsmanager.update_secret(SecretId=secret,SecretString=NewSecret)
        print(secret + " secret has been updated with latest key details for " + secret_details['UserName'] + " user.")
        
    return "Key deletion, creation and secret update has completed successfully."