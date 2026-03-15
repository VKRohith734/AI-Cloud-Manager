import os
import time
import threading
import datetime
import boto3
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel as FastAPIBaseModel
import uvicorn


from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import TypedDict, Literal
from pydantic import Field, BaseModel
from langgraph.graph import START, END, StateGraph

# Load environment variables from .env file
load_dotenv()

# --- Global Dashboard State ---
global_logs = []
global_chat = []
total_savings = 0.0

def add_log(msg):
    now_str = datetime.datetime.now().strftime("%I:%M %p")
    global_logs.append(f"[{now_str}] {msg}")
    print(f"LOG: {msg}")

def add_chat(sender, text):
    global_chat.append({"sender": sender, "text": text})

add_log("System initialized securely. Monitoring active.")

from langchain_aws import ChatBedrockConverse
from botocore.exceptions import ClientError

def get_llm():
    return ChatBedrockConverse(
        model="us.amazon.nova-lite-v1:0",  # or nova‑pro / nova‑micro / nova‑2‑lite
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
    )

class Route(BaseModel):
    step: Literal["EC2", "S3", "VPC", "chatbot"] = Field(description="The next routing step based on the prompt")

class Route1(BaseModel):
    step: Literal["create", "upload"] = Field(description="The next step for AWS S3")
    bucket_name: str = Field(default="", description="The specific S3 bucket name mentioned by the user, if any.")

class Route2(BaseModel):
    step: Literal["create", "start", "stop", "terminate"] = Field(description="The next step for AWS EC2")
    instance_id: str = Field(default="", description="The specific EC2 instance ID mentioned by the user (like i-xxxx), if any.")

class State(TypedDict):
    input: str
    decision: str
    decision1: str
    decision2: str
    ID: str
    bucket_name: str
    bot_response: str

# --- Node Functions ---
def llm_call_route(state: State):
    user_input = state.get("input", "").lower()
    
    # 1. Immediate Manual Mock Override for Hackathon (No API Key needed)
    if "savings" in user_input or "money" in user_input:
        return {"decision": "chatbot"}
    
    # 2. General FAQ
    if user_input.startswith(("what", "who", "how", "explain")):
        return {"decision": "chatbot"}
        
    # 3. Fallback to LangGraph Router
    try:
        llm = get_llm()
        router = llm.with_structured_output(Route)
        decision = router.invoke([
            SystemMessage(content="This will route the user input to exactly one of: chatbot, EC2, S3, or VPC."),
            HumanMessage(content=user_input)
        ])
        decision_step = decision.step
    except Exception as e:
        print(f"LLM Routing Error: {e}")
        # Default fallback if LLM is unreachable due to keys
        decision_step = "chatbot"
        
    return {"decision": decision_step}

def route_decision(state: State):
    decision = state.get("decision")
    # Add a mock translation map for the manual overrides
    if decision == "EC2_Q" or decision == "EC2": return "EC2_Q"
    elif decision == "S3": return "S3_Q"
    elif decision == "VPC": return "VPC_Q"
    else: return "chatbot"

# --- S3 Operations ---
def S3_Q(state: State):
    try:
        llm = get_llm()
        router1 = llm.with_structured_output(Route1)
        decision1 = router1.invoke([
            SystemMessage(content="Route the input to either 'create' (create bucket) or 'upload' (upload file). Extract any mentioned S3 bucket name if present."),
            HumanMessage(content=state.get("input", ""))
        ])
        d1_step = decision1.step
        bucket_name = decision1.bucket_name
    except:
        d1_step = "create"
        bucket_name = ""
    
    target_bucket = bucket_name if bucket_name else "dct-crud-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return {"decision1": d1_step, "bucket_name": target_bucket}

def route_decision1(state: State):
    return "create" if state.get("decision1") == "create" else "upload"

def create(state: State):
    s3 = boto3.resource('s3')
    bucket_name = state.get("bucket_name", "dct-crud-default-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    msg = ""
    try:
        existing_buckets = [b.name for b in s3.buckets.all()]
        if bucket_name not in existing_buckets:
            msg = f"'{bucket_name}' bucket does not exist. Creating now..."
            s3.create_bucket(Bucket=bucket_name)
        else:
            msg = f"'{bucket_name}' bucket already exists!"
        add_log(msg)
    except Exception as e:
        msg = f"Error creating S3 bucket: {e}"
        add_log(msg)
    return {"bucket_name": bucket_name, "bot_response": msg}

def upload(state: State):
    s3 = boto3.resource('s3')
    bucket_name = state.get("bucket_name", "dct-crud-1-20260303")
    file_1 = "example_upload.txt"
    msg = ""
    if not os.path.exists(file_1):
        try:
            with open(file_1, "w") as f:
                f.write("Placeholder content for S3 upload testing.")
        except Exception:
            pass
    try:
        s3.Bucket(bucket_name).upload_file(Filename=file_1, Key=os.path.basename(file_1))
        msg = f"Successfully uploaded {file_1} to {bucket_name}"
    except Exception as e:
        msg = f"Error uploading file to S3: {e}"
    add_log(msg)
    return {"bot_response": msg}

# --- EC2 Operations ---
def EC2_Q(state: State):
    user_input = state.get("input", "").lower()
    
    # Extract Instance ID cleanly (e.g. "start instance i-1234")
    embedded_id = ""
    words = user_input.split()
    for word in words:
        # Strip punctuation that might be attached to the ID from user typing
        clean_word = "".join(c for c in word if c.isalnum() or c == '-')
        if clean_word.startswith("i-") and len(clean_word) > 5:
            embedded_id = clean_word
            break
            
    # LLM Extraction
    try:
        llm = get_llm()
        router2 = llm.with_structured_output(Route2)
        decision2 = router2.invoke([
            SystemMessage(content="Route the input to one of the following EC2 actions: create, start, stop, terminate. Crucially, extract any mentioned instance-id (e.g., i-0abcdef1234) from the prompt if present."),
            HumanMessage(content=state.get("input", ""))
        ])
        
        # Determine the target Instance ID. Preference to the one found in the prompt.
        found_id = getattr(decision2, 'instance_id', "")
        target_id = found_id if found_id else (embedded_id if embedded_id else state.get("ID", ""))
        
        return {"decision2": decision2.step, "ID": target_id}
    except Exception as e:
         return {"decision2": "create_instance"}

def route_decision2(state: State):
    mapping = {
        "create": "create_instance",
        "start": "start_instance",
        "stop": "stop_instance",
        "terminate": "terminate_instance"
    }
    return mapping.get(state.get("decision2"), "create_instance")

def create_instance(state: State):
    ec2 = boto3.resource("ec2")
    msg = ""
    instance_id = "error_id"
    try:
        ssm = boto3.client('ssm', region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        ami_response = ssm.get_parameter(Name='/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64')
        ami_id = ami_response['Parameter']['Value']
        
        new_instance = ec2.create_instances(
            ImageId=ami_id,
            MinCount=1, MaxCount=1, InstanceType='t3.micro',
            TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'dt-ec2-hol'}]}]
        )
        instance_id = str(new_instance[0].id)
        msg = f"Instance created successfully with ID: {instance_id}"
    except Exception as e:
        msg = f"Error creating EC2 instance: {e}"
    add_log(msg)
    return {"ID": instance_id, "bot_response": msg}

def start_instance(state: State):
    ec2 = boto3.resource("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            client = boto3.client('ec2', region_name='us-east-1')
            reservations = client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['stopped', 'pending']}]).get("Reservations", [])
            stopped_instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(stopped_instances) > 0:
                instance_id = stopped_instances[0]
                msg += f"Auto-selected stopped instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            ec2.Instance(instance_id).start()
            msg += f"Instance {instance_id} has been commanded to start."
        except Exception as e:
            msg = f"Error starting instance: {e}"
    else:
        msg = "No stopped instance found to start. You can type 'create instance' to spawn a new one, or specify an ID (e.g., 'start instance i-12345')."
    add_log(msg)
    return {"bot_response": msg}

def stop_instance(state: State):
    ec2 = boto3.resource("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            client = boto3.client('ec2', region_name='us-east-1')
            reservations = client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]).get("Reservations", [])
            running_instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(running_instances) > 0:
                instance_id = running_instances[0]
                msg += f"Auto-selected running instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            ec2.Instance(instance_id).stop()
            msg += f"Instance {instance_id} has been commanded to stop."
        except Exception as e:
            msg = f"Error stopping instance: {e}"
    else:
         msg = "No running instance found to stop. Please specify an instance ID or type 'create instance'."
    add_log(msg)
    return {"bot_response": msg}

def terminate_instance(state: State):
    ec2 = boto3.resource("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            client = boto3.client('ec2', region_name='us-east-1')
            reservations = client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}]).get("Reservations", [])
            instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(instances) > 0:
                instance_id = instances[0]
                msg += f"Auto-selected instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            ec2.Instance(instance_id).terminate()
            msg += f"Instance {instance_id} has been terminated."
        except Exception as e:
            msg = f"Error terminating instance: {e}"
    else:
         msg = "No instances found to terminate. Please specify an instance ID or type 'create instance'."
    add_log(msg)
    return {"bot_response": msg}

# --- VPC Operations ---
def VPC_Q(state: State):
    ec2 = boto3.client('ec2')
    vpc_name = 'vpc-hol'
    msg = ""
    try:
        response = ec2.describe_vpcs(Filters=[{'Name': 'tag:Name', 'Values': [vpc_name]}])
        vpcs = response.get('Vpcs', [])
        if vpcs:
            vpc_id = vpcs[0]['VpcId']
            msg = f"VPC '{vpc_name}' with ID '{vpc_id}' already exists."
        else:
            vpc_response = ec2.create_vpc(CidrBlock='10.0.0.0/16')
            vpc_id = vpc_response['Vpc']['VpcId']
            time.sleep(2)
            ec2.create_tags(Resources=[vpc_id], Tags=[{'Key': 'Name', 'Value': vpc_name}])
            msg = f"VPC '{vpc_name}' with ID '{vpc_id}' has been created."
    except Exception as e:
        msg = f"Error checking/creating VPC: {e}"
    add_log(msg)
    return {"bot_response": msg}

# --- Chatbot Operations ---
def chatbot(state: State):
    user_input = state.get("input", "").lower()
    
    if "savings" in user_input or "money" in user_input:
        state["bot_response"] = f"Your current AI auto-stop savings is ${total_savings:.2f}. Instances with <5% CPU are stopped automatically to save $0.45/hr."
        return state
         
    try:
        llm = get_llm()
        answer = llm.invoke(input=[
            SystemMessage(content="You are a helpful AWS Cloud Manager assistant. Answer clearly and concisely."),
            HumanMessage(content=state.get("input", ""))
        ])
        state["bot_response"] = answer.content
    except ClientError as e:
        if "AccessDeniedException" in str(e):
            state["bot_response"] = "I am unable to connect to Amazon Nova because your AWS IAM user does not have permission to use Bedrock (bedrock:InvokeModel). However, you can still type commands like 'Start instance i-xxxx'!"
        else:
             state["bot_response"] = f"A cloud API error occurred: {e}"
    except Exception as e:
         state["bot_response"] = "I am unable to connect to Amazon Nova because the API key might be missing or invalid. However, you can still type commands like 'Start instance i-xxxx' to manage your EC2 servers directly!"
    return state

# --- Build Graph ---
builder = StateGraph(State)
builder.add_node("llm_call_route", llm_call_route)
builder.add_node("S3_Q", S3_Q)
builder.add_node("create", create)
builder.add_node("upload", upload)
builder.add_node("EC2_Q", EC2_Q)
builder.add_node("start_instance", start_instance)
builder.add_node("stop_instance", stop_instance)
builder.add_node("create_instance", create_instance)
builder.add_node("VPC_Q", VPC_Q)
builder.add_node("chatbot", chatbot)
builder.add_node("terminate_instance", terminate_instance)

builder.add_edge(START, "llm_call_route")
builder.add_conditional_edges("llm_call_route", route_decision, {"S3_Q": "S3_Q", "EC2_Q": "EC2_Q", "VPC_Q": "VPC_Q", "chatbot": "chatbot"})
builder.add_conditional_edges("S3_Q", route_decision1, {"create": "create", "upload": "upload"})
builder.add_conditional_edges("EC2_Q", route_decision2, {"create_instance": "create_instance", "start_instance": "start_instance", "stop_instance": "stop_instance", "terminate_instance": "terminate_instance"})
builder.add_edge("create", END)
builder.add_edge("upload", END)
builder.add_edge("create_instance", END)
builder.add_edge("start_instance", END)
builder.add_edge("stop_instance", END)
builder.add_edge("terminate_instance", END)
builder.add_edge("VPC_Q", END)
builder.add_edge("chatbot", END)

graph = builder.compile()


# --- Background Thread for Auto-stop ---
def monitor_and_stop_idle_instances():
    global total_savings
    ec2 = boto3.client('ec2')
    cloudwatch = boto3.client('cloudwatch')
    
    while True:
        try:
            instances = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
            running_instance_ids = [i['InstanceId'] for r in instances.get('Reservations', []) for i in r.get('Instances', [])]
            for inst_id in running_instance_ids:
                now = datetime.datetime.utcnow()
                past_5_mins = now - datetime.timedelta(minutes=5)
                metrics = cloudwatch.get_metric_statistics(
                    Namespace='AWS/EC2', MetricName='CPUUtilization',
                    Dimensions=[{'Name': 'InstanceId', 'Value': inst_id}],
                    StartTime=past_5_mins, EndTime=now, Period=60, Statistics=['Average']
                )
                datapoints = metrics.get('Datapoints', [])
                if not datapoints: continue
                
                datapoints.sort(key=lambda x: x['Timestamp'])
                latest_points = datapoints[-2:]
                
                is_idle = True
                for point in latest_points:
                    if point['Average'] >= 5.0:
                        is_idle = False
                        break
                
                if is_idle and len(latest_points) > 0:
                    msg = f"Instance {inst_id} detected as IDLE (<5% CPU). Auto-stopping to save costs..."
                    add_log(msg)
                    ec2.stop_instances(InstanceIds=[inst_id])
                    total_savings += 0.45
        except Exception as e:
            pass # Suppress output so it doesn't spam logs
            
        time.sleep(120)

# --- FastAPI App ---
app = FastAPI(title="AI Cloud Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def get_index():
    with open("AICloudManager/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/style.css")
def get_css():
    with open("AICloudManager/style.css", "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/css")

@app.get("/script.js")
def get_js():
    with open("AICloudManager/script.js", "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")

@app.on_event("startup")
def startup_event():
    # Start the idle auto-stop background thread
    monitor_thread = threading.Thread(target=monitor_and_stop_idle_instances, daemon=True)
    monitor_thread.start()

class AWSCredentials(FastAPIBaseModel):
    aws_access_key_id: str
    aws_secret_access_key: str
    region_name: str

@app.post("/api/credentials")
def set_credentials(creds: AWSCredentials):
    os.environ['AWS_ACCESS_KEY_ID'] = creds.aws_access_key_id
    os.environ['AWS_SECRET_ACCESS_KEY'] = creds.aws_secret_access_key
    os.environ['AWS_DEFAULT_REGION'] = creds.region_name
    
    boto3.setup_default_session(
        aws_access_key_id=creds.aws_access_key_id,
        aws_secret_access_key=creds.aws_secret_access_key,
        region_name=creds.region_name
    )
    
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        add_log(f"AWS connected successfully. Identity: {identity.get('Arn')}")
        return {"message": "Connected successfully!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/s3-buckets")
def get_s3_buckets():
    try:
        s3 = boto3.client('s3')
        response = s3.list_buckets()
        buckets = [b['Name'] for b in response.get('Buckets', [])]
        return {"buckets": buckets}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/upload")
async def s3_upload(file: UploadFile = File(...), bucket_name: str = Form(...)):
    try:
        s3 = boto3.client('s3')
        s3.upload_fileobj(file.file, bucket_name, file.filename)
        msg = f"Successfully uploaded {file.filename} to {bucket_name}"
        add_log(msg)
        return {"message": msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class ChatRequest(FastAPIBaseModel):
    message: str

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    add_chat("user", req.message)
    add_log(f"User Command Received: {req.message}")
    
    try:
        result = graph.invoke({"input": req.message})
        bot_resp = result.get("bot_response", "Action complete.")
    except Exception as e:
        bot_resp = f"Error processing command: {e}"
        
    add_chat("bot", bot_resp)
    return {"status": "success"}

@app.get("/api/dashboard")
def get_dashboard():
    ec2 = boto3.client('ec2')
    cloudwatch = boto3.client('cloudwatch')
    instances_data = []
    
    try:
        reservations = ec2.describe_instances().get("Reservations", [])
        for r in reservations:
            for inst in r.get("Instances", []):
                inst_id = inst["InstanceId"]
                state_name = inst["State"]["Name"]
                status = "Stopped"
                action_text = ""
                cpu_val = 0
                
                if state_name == "running":
                    status = "Running"
                    
                    # Fetch immediate CPU usage
                    now = datetime.datetime.utcnow()
                    past = now - datetime.timedelta(minutes=5)
                    metrics = cloudwatch.get_metric_statistics(
                        Namespace='AWS/EC2', MetricName='CPUUtilization',
                        Dimensions=[{'Name': 'InstanceId', 'Value': inst_id}],
                        StartTime=past, EndTime=now, Period=300, Statistics=['Average']
                    )
                    dps = metrics.get('Datapoints', [])
                    if dps:
                        dps.sort(key=lambda x: x['Timestamp'])
                        cpu_val = int(dps[-1]['Average'])
                        
                    if cpu_val < 5:
                        status = "Idle"
                        action_text = "Monitoring (<5% CPU) - Preparing auto-stop"
                    elif cpu_val > 80:
                        action_text = "High Output (>80%) - AI scaling preparing"
                    else:
                        action_text = "Optimal Performance"
                        
                elif state_name == "stopped":
                    status = "Stopped"
                    action_text = "Instance is sleeping (Cost Saved)"
                elif state_name in ["shutting-down", "terminated"]:
                    status = "Terminated"
                    action_text = "Instance permanently terminated"
                else:
                    status = "Pending"
                    action_text = "Provisioning instance..."

                instances_data.append({
                    "id": inst_id,
                    "status": status,
                    "cpu": cpu_val,
                    "action": action_text
                })
    except Exception as e:
        pass # In a real system, log to a secure store.
        
    running_count = sum(1 for x in instances_data if x['status'] in ['Running', 'Idle'])
    stopped_count = sum(1 for x in instances_data if x['status'] == 'Stopped')

    # Return structured data that matches the frontend UI expectations
    return {
        "instances": instances_data,
        "logs": list(reversed(global_logs[-20:])), # Reverse to show newest on top
        "chat": global_chat[-50:],
        "savings": f"{total_savings:.2f}",
        "totalCount": len(instances_data),
        "runningCount": running_count,
        "runRate": running_count * 0.45,
        "savingsRate": stopped_count * 0.45
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)