import os
import zipfile
import boto3
import time
import base64
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

# We need the user's AWS credentials from their environment to do this
aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

def zip_directory(folder_path, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            if '__pycache__' in root or '.git' in root or '.venv' in root:
                continue
            for file in files:
                if file.endswith('.zip') or file == 'deploy_aws.py':
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, folder_path)
                zipf.write(file_path, arcname)

def deploy():
    print("Starting automated deployment to AWS EC2...")
    
    # 1. Zip the app
    zip_filename = 'app_deployment.zip'
    print("Zipping the application...")
    zip_directory('.', zip_filename)
    
    session = boto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region
    )
    
    ec2_client = session.client('ec2')
    s3_client = session.client('s3')
    
    # 2. Create S3 Bucket (if we need to host the zip) or upload to existing
    # Just in case the default bucket is not there, we create a temporary one or use a public object.
    bucket_name = f'jankai-deploy-{int(time.time())}'
    print(f"Creating S3 bucket: {bucket_name}")
    try:
        s3_client.create_bucket(Bucket=bucket_name)
    except Exception as e:
        print(f"S3 Error: {e}")
        # Try generic
        bucket_name = 'dct-crud-1-20260303'
        print(f"Falling back to bucket: {bucket_name}")
        
    print("Uploading app zip to S3...")
    s3_client.upload_file(zip_filename, bucket_name, zip_filename)
    
    # Generate presigned URL valid for 1 hour for the EC2 instance to download
    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': zip_filename},
        ExpiresIn=3600
    )
    
    # 3. Create Security Group for HTTP (80)
    sg_name = f'aicloud-manager-sg-{int(time.time())}'
    print(f"Creating Security Group: {sg_name}")
    sg_id = None
    try:
        response = ec2_client.create_security_group(
            GroupName=sg_name,
            Description='Allow port 80 and 22 for AI Cloud Manager'
        )
        sg_id = response['GroupId']
        print(f"Security Group ID: {sg_id}")
        
        # Add Rules
        ec2_client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 80,
                    'ToPort': 80,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }
            ]
        )
    except ClientError as e:
        print(e)
        return
        
    # 4. Launch EC2 Instance with UserData
    print("Launching EC2 instance...")
    
    # Use Amazon Linux 2023 AMI in us-east-1
    ami_id = 'ami-0f3caa1cf4417e51b' 
    
    # Create KeyPair for debugging
    key_name = f'aicloud-debug-key-{int(time.time())}'
    try:
        key_pair = ec2_client.create_key_pair(KeyName=key_name)
        with open(f'{key_name}.pem', 'w') as f:
            f.write(key_pair['KeyMaterial'])
        print(f"Created KeyPair: {key_name}.pem")
    except Exception as e:
        print(f"Could not create KeyPair: {e}")

    user_data_script = f"""#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting UserData script..."
yum update -y
yum install -y python3 python3-pip unzip wget

mkdir -p /home/ec2-user/app
cd /home/ec2-user/app

echo "Downloading app payload..."
wget -O app.zip "{presigned_url}"

echo "Unzipping..."
unzip app.zip

echo "Installing requirements..."
python3 -m venv /home/ec2-user/app/venv
/home/ec2-user/app/venv/bin/pip3 install -r requirements.txt

echo "Modifying port from 5000 to 80..."
sed -i 's/port=5000/port=80/g' "AI Cloud manager.py"

echo "Creating systemd service..."
cat <<EOF > /etc/systemd/system/aicloud.service
[Unit]
Description=AI Cloud Manager Application
After=network.target

[Service]
User=root
WorkingDirectory=/home/ec2-user/app
ExecStart=/home/ec2-user/app/venv/bin/python3 "AI Cloud manager.py"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aicloud
systemctl start aicloud
echo "UserData script completed."
"""
    
    ec2_resource = session.resource('ec2')
    instances = ec2_resource.create_instances(
        ImageId=ami_id,
        MinCount=1,
        MaxCount=1,
        KeyName=key_name,
        InstanceType='t3.micro',
        SecurityGroupIds=[sg_id],
        UserData=user_data_script,
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': 'AI-Cloud-Manager-Prod'}]
            }
        ]
    )
    
    instance = instances[0]
    print(f"Instance {instance.id} created. Waiting for it to enter 'running' state...")
    instance.wait_until_running()
    instance.reload()
    
    public_ip = instance.public_ip_address
    print("\n" + "="*50)
    print("DEPLOYMENT SUCCESSFUL!")
    print("="*50)
    print(f"Your application is being deployed to the cloud instead of your computer.")
    print(f"It may take 2-3 minutes for the software to install and start.")
    print(f"You can view your running app permanently here:")
    print(f"==> http://{public_ip}")
    print("="*50)

if __name__ == "__main__":
    deploy()
