import boto3
import json
import os
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """Secrets Manager RDS Password Rotation Lambda - Support multiple RDS instances"""
    print(f"Starting password rotation with event: {event}")
    arn = event['SecretId']
    token = event['ClientRequestToken']
    step = event['Step']
    # Setup the clients，必须使用显式的endpoint_url
    rds_client = boto3.client(
    'rds',
    endpoint_url='https://vpce-0732d855d3aaaabbb-9vdxuk3l.rds.cn-northwest-1.vpce.amazonaws.com.cn'
    )
    secrets_client = boto3.client('secretsmanager')

    # Verify rotation status
    print("Checkin g secret metadata and rotation status...")
    metadata = secrets_client.describe_secret(SecretId=arn)
    if not metadata['RotationEnabled']:
        print(f"ERROR: Secret {arn} is not enabled for rotation")
        raise ValueError(f"Secret {arn} is not enabled for rotation")
    
    versions = metadata['VersionIdsToStages']
    print(f"Current version stages: {versions}")

    if token not in versions:
        print(f"ERROR: Version {token} not found in version stages")
        raise ValueError(f"Secret version {token} has no stage for rotation of secret {arn}")

    if "AWSCURRENT" in versions[token]:
        print("Secret version is already marked as AWSCURRENT. Exiting.")
        return
    elif "AWSPENDING" not in versions[token]:
        print(f"ERROR: Version {token} not in AWSPENDING stage")
        raise ValueError(f"Secret version {token} not set as AWSPENDING for secret {arn}")
   
    # Execute rotation steps
    if step == "createSecret":
        create_secret(secrets_client, arn, token, rds_client)
    elif step == "setSecret":
        wait_for_db_availability(rds_client, secrets_client, arn, token)
    elif step == "testSecret":
        check_rds_status(rds_client, secrets_client, arn, token)
    elif step == "finishSecret":
        finish_secret(secrets_client, arn, token)
    else:
        raise ValueError("Invalid step parameter")


def create_secret(secrets_client, arn, token, rds_client):
    """Generate new password and update RDS instance"""
    print(f"Starting create_secret step for secret: {arn}")
    print(f"Token: {token}")

    # Check if this version already has AWSPENDING stage
    try:
        print(f"Checking if version {token} already exists with AWSPENDING stage...")
        response = secrets_client.get_secret_value(
            SecretId=arn, 
            VersionId=token, 
            VersionStage="AWSPENDING"
        )
        print(f"Version {token} already exists with AWSPENDING stage. Skipping creation.")
        print(f"Existing secret: {response['SecretString'][:50]}...")
        return
    except secrets_client.exceptions.ResourceNotFoundException:
        print(f"Version {token} does not exist yet. Proceeding with creation.")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            print(f"Version {token} does not exist yet. Proceeding with creation.")
        elif error_code == 'InvalidRequestException':
            print(f"Version {token} exists but not in AWSPENDING stage. Proceeding.")
        else:
            print(f"Unexpected error checking version: {e}")
            raise

    # Generate new password
    print("Generating new random password...")
    new_password = get_random_password(secrets_client)
    print(f"Successfully generated new password (length: {len(new_password)})")

    try:
        # Get RDS instance info from Secret
        print("Retrieving current secret value...")
        current_secret = get_secret_dict(secrets_client, arn, "AWSCURRENT")
        db_instance_id = current_secret['dbInstanceIdentifier']
        master_username = current_secret['username']
        
        print(f"DB Instance: {db_instance_id}, Username: {master_username}")

        # Build new Secret content
        secret_dict = {
            'dbInstanceIdentifier': db_instance_id,
            'username': master_username,
            'password': new_password,
            'engine': current_secret.get('engine', 'mysql')
        }
        
        # Store new password to AWSPENDING
        print(f"Storing new secret value with token {token} in AWSPENDING stage...")
        secrets_client.put_secret_value(
            SecretId=arn,
            ClientRequestToken=token,
            SecretString=json.dumps(secret_dict),
            VersionStages=['AWSPENDING']
        )
        print("Successfully stored new secret value in AWSPENDING stage")

        # Update password via RDS API
        print(f"Updating password in RDS instance: {db_instance_id}")
        rds_client.modify_db_instance(
            DBInstanceIdentifier=db_instance_id,
            MasterUserPassword=new_password,
            ApplyImmediately=True
        )
        print(f"Successfully initiated password update for RDS instance {db_instance_id}")

    except ClientError as e:
        print(f"ERROR in create_secret: {str(e)}")
        print(f"Error code: {e.response['Error']['Code']}")
        print(f"Error message: {e.response['Error']['Message']}")
        raise ValueError(f"Error creating secret: {str(e)}")


def wait_for_db_availability(rds_client, secrets_client, arn, token):
    """Wait for RDS instance to become available"""
    print(f"Starting set_secret step for secret: {arn}")
    try:
        # Get RDS instance ID from AWSPENDING
        pending_secret = get_secret_dict(secrets_client, arn, "AWSPENDING", token)
        db_instance_id = pending_secret['dbInstanceIdentifier']
        
        print(f"Waiting for DB instance {db_instance_id} to become available...")

        waiter = rds_client.get_waiter('db_instance_available')
        waiter.wait(
            DBInstanceIdentifier=db_instance_id,
            WaiterConfig={
                'Delay': 30,
                'MaxAttempts': 20
            }
        )
        print(f"DB instance {db_instance_id} is now available")

    except ClientError as e:
        print(f"ERROR in checking for Database availability: {str(e)}")
        raise ValueError(f"Error for Database availability: {str(e)}")


def check_rds_status(rds_client, secrets_client, arn, token):
    """Check RDS instance status and display new password"""
    print(f"Starting check_rds_status step for secret: {arn}")
    try:
        # Get info from AWSPENDING
        pending_secret = get_secret_dict(secrets_client, arn, "AWSPENDING", token)
        db_instance_id = pending_secret['dbInstanceIdentifier']
        
        print(f"Checking status of DB instance: {db_instance_id}")

        response = rds_client.describe_db_instances(
            DBInstanceIdentifier=db_instance_id
        )
        status = response['DBInstances'][0]['DBInstanceStatus']
        endpoint = response['DBInstances'][0]['Endpoint']['Address']
        
        print(f"Current DB instance status: {status}")
        print(f"DB Endpoint: {endpoint}")

        if status != 'available':
            print(f"ERROR: Database is not available. Current status: {status}")
            raise ValueError("Database is not available")

        # Display new password info (for testing, remove in production)
        print(f"=== New Password Info ===")
        print(f"RDS Instance: {db_instance_id}")
        print(f"Username: {pending_secret['username']}")
        print(f"New Password: {pending_secret['password']}")
        print(f"Engine: {pending_secret.get('engine', 'mysql')}")
        print(f"========================")

        print("Successfully verified database availability")

    except ClientError as e:
        print(f"ERROR in checking rds status: {str(e)}")
        raise ValueError(f"Error checking rds status: {str(e)}")


def finish_secret(secrets_client, arn, token):
    """Finish rotation, mark AWSPENDING as AWSCURRENT"""
    print(f"Starting finish_secret step for secret: {arn}")
    try:
        print("Retrieving secret metadata...")
        metadata = secrets_client.describe_secret(SecretId=arn)
        current_version = None

        for version in metadata["VersionIdsToStages"]:
            if "AWSCURRENT" in metadata["VersionIdsToStages"][version]:
                current_version = version
                break

        print(f"Current version: {current_version}")
        print(f"Updating secret version stage from {current_version} to {token}")

        secrets_client.update_secret_version_stage(
            SecretId=arn,
            VersionStage="AWSCURRENT",
            MoveToVersionId=token,
            RemoveFromVersionId=current_version
        )
        print("Successfully updated secret version to AWSCURRENT")

    except ClientError as e:
        print(f"ERROR in finish_secret: {str(e)}")
        raise ValueError(f"Error finishing secret: {str(e)}")


def get_secret_dict(service, secret_arn, stage, token=None):
    """Get Secret content for specified version and parse as dict"""
    kwargs = {'SecretId': secret_arn, 'VersionStage': stage}
    if token:
        kwargs['VersionId'] = token
    
    response = service.get_secret_value(**kwargs)
    return json.loads(response['SecretString'])


def get_environment_bool(variable_name, default_value):
    """Convert environment variable to boolean"""
    variable = os.environ.get(variable_name, str(default_value))
    return variable.lower() in ['true', '1', 'y', 'yes']


def get_random_password(secrets_client):
    """Generate random password"""
    passwd = secrets_client.get_random_password(
        ExcludeCharacters=os.environ.get('EXCLUDE_CHARACTERS', ':/@"\'\\'),
        PasswordLength=int(os.environ.get('PASSWORD_LENGTH', 32)),
        ExcludeNumbers=get_environment_bool('EXCLUDE_NUMBERS', False),
        ExcludePunctuation=get_environment_bool('EXCLUDE_PUNCTUATION', False),
        ExcludeUppercase=get_environment_bool('EXCLUDE_UPPERCASE', False),
        ExcludeLowercase=get_environment_bool('EXCLUDE_LOWERCASE', False),
        RequireEachIncludedType=get_environment_bool('REQUIRE_EACH_INCLUDED_TYPE', True)
    )
    return passwd['RandomPassword']
