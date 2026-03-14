import os
import time
import threading
import datetime
import boto3
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel as FastAPIBaseModel
import uvicorn

from langchain_openai import ChatOpenAI
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

# --- Global AWS Credentials ---
aws_credentials = {
    "aws_access_key_id": None,
    "aws_secret_access_key": None,
    "region_name": "us-east-1"
}

def get_boto3_client(service_name):
    if aws_credentials["aws_access_key_id"] and aws_credentials["aws_secret_access_key"]:
        return boto3.client(
            service_name,
            aws_access_key_id=aws_credentials["aws_access_key_id"],
            aws_secret_access_key=aws_credentials["aws_secret_access_key"],
            region_name=aws_credentials["region_name"]
        )
    return boto3.client(service_name) # Fallback to environment/profile

def get_boto3_resource(service_name):
    if aws_credentials["aws_access_key_id"] and aws_credentials["aws_secret_access_key"]:
        return boto3.resource(
            service_name,
            aws_access_key_id=aws_credentials["aws_access_key_id"],
            aws_secret_access_key=aws_credentials["aws_secret_access_key"],
            region_name=aws_credentials["region_name"]
        )
    return boto3.resource(service_name) # Fallback to environment/profile

def add_log(msg):
    now_str = datetime.datetime.now().strftime("%I:%M %p")
    global_logs.append(f"[{now_str}] {msg}")
    print(f"LOG: {msg}")

def add_chat(sender, text):
    global_chat.append({"sender": sender, "text": text})

add_log("System initialized securely. Monitoring active.")

# --- LangGraph Setup ---
llm = ChatOpenAI(model="gpt-4o-mini")

class Route(BaseModel):
    step: Literal["EC2", "S3", "VPC", "chatbot"] = Field(description="The next routing step based on the prompt")

class Route1(BaseModel):
    step: Literal["create", "upload"] = Field(description="The next step for AWS S3")

class Route2(BaseModel):
    step: Literal["create", "start", "stop", "terminate"] = Field(description="The next step for AWS EC2")
    instance_id: str = Field(default="", description="The specific EC2 instance ID mentioned by the user (like i-xxxx), if any.")
    
router = llm.with_structured_output(Route)
router1 = llm.with_structured_output(Route1)
router2 = llm.with_structured_output(Route2)

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
    if "start" in user_input and "instance" in user_input:
        return {"decision": "EC2_Q"}
    elif "stop" in user_input and "instance" in user_input:
         return {"decision": "EC2_Q"}
    elif "terminate" in user_input and "instance" in user_input:
         return {"decision": "EC2_Q"}
    elif "create" in user_input and "instance" in user_input:
         return {"decision": "EC2_Q"}
    
    # 2. General FAQ
    if user_input.startswith(("what", "who", "how", "explain")):
        return {"decision": "chatbot"}
        
    # 3. Fallback to LangGraph Router (will fail if API key bad, but wrapped in try/except)
    try:
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
        decision1 = router1.invoke([
            SystemMessage(content="Route the input to either 'create' (create bucket) or 'upload' (upload file)."),
            HumanMessage(content=state.get("input", ""))
        ])
        d1_step = decision1.step
    except:
        d1_step = "create"
    return {"decision1": d1_step}

def route_decision1(state: State):
    return "create" if state.get("decision1") == "create" else "upload"

def create(state: State):
    s3 = boto3.resource('s3')
    bucket_name = "dct-crud-1-20260303"
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
            
    # Manual Override Routing (No API Key)
    if "start" in user_input:
        return {"decision2": "start", "ID": embedded_id}
    elif "stop" in user_input:
        return {"decision2": "stop", "ID": embedded_id}
    elif "terminate" in user_input:
        return {"decision2": "terminate", "ID": embedded_id}
        
    # Fallback to LLM Extraction
    try:
        decision2 = router2.invoke([
            SystemMessage(content="Route the input to one of the following EC2 actions: create, start, stop, terminate. Crucially, extract any mentioned instance-id (e.g., i-0abcdef1234) from the prompt if present."),
            HumanMessage(content=state.get("input", ""))
        ])
        
        # Determine the target Instance ID. Preference to the one found in the prompt.
        found_id = getattr(decision2, 'instance_id', None)
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
        new_instance = ec2.create_instances(
            ImageId='ami-0f3caa1cf4417e51b',
            MinCount=1, MaxCount=1, InstanceType='t3.micro', KeyName='usa-east-kp',
            TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'dt-ec2-hol'}]}]
        )
        instance_id = str(new_instance[0].id)
        msg = f"Instance created successfully with ID: {instance_id}"
    except Exception as e:
        msg = f"Error creating EC2 instance: {e}"
    add_log(msg)
    return {"ID": instance_id, "bot_response": msg}

def list_instances():
    """Returns a list of all instances in the account."""
    ec2 = get_boto3_resource('ec2')
    instances_list = []
    for instance in ec2.instances.all():
        name = "Unknown"
        for tag in instance.tags or []:
            if tag['Key'] == 'Name':
                name = tag['Value']
                break
        
        status = instance.state['Name']
        hours_running = 0
        
        instances_list.append({
            "id": instance.id,
            "name": name,
            "status": status,
            "type": instance.instance_type,
            "launch_time": instance.launch_time,
            "hours_running": hours_running # Placeholder, needs calculation
        })
    return instances_list

def check_cpu_utilization(instance_id):
    """
    Fetches real CPU utilization from AWS CloudWatch over the last 10 minutes.
    Returns the most recent Average CPU data point available.
    """
    cw = get_boto3_client('cloudwatch')
    
    # CloudWatch basic monitoring updates every 5 minutes, so we look back 10 mins 
    # to ensure we capture at least one recent data point.
    end_time = datetime.datetime.utcnow()
    start_time = end_time - datetime.timedelta(minutes=10)
    
    try:
        response = cw.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[
                {
                    'Name': 'InstanceId',
                    'Value': instance_id
                },
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=300, # 5 minute intervals (300 seconds)
            Statistics=['Average']
        )
        
        datapoints = response.get('Datapoints', [])
        
        if not datapoints:
            return 0  # No data available yet (e.g. instance just launched)
            
        # CloudWatch doesn't guarantee order, so sort by Timestamp to get the latest
        latest_datapoint = sorted(datapoints, key=lambda x: x['Timestamp'])[-1]
        
        # Return percentage rounded to 1 decimal place
        return round(latest_datapoint['Average'], 1)
        
    except Exception as e:
        print(f"Error fetching CloudWatch data for {instance_id}: {e}")
        return 0

def manage_instance(instance_id, action):
    """Starts, stops, or terminates an EC2 instance."""
    ec2_client = get_boto3_client('ec2')
    
    if action == "start":
        ec2_client.start_instances(InstanceIds=[instance_id])
    elif action == "stop":
        ec2_client.stop_instances(InstanceIds=[instance_id])
    elif action == "terminate":
        ec2_client.terminate_instances(InstanceIds=[instance_id])
    else:
        raise ValueError(f"Invalid action {action}")

def start_instance(state: State):
    ec2_client = get_boto3_client("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            reservations = ec2_client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['stopped', 'pending']}]).get("Reservations", [])
            stopped_instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(stopped_instances) > 0:
                instance_id = stopped_instances[0]
                msg += f"Auto-selected stopped instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            manage_instance(instance_id, "start")
            msg += f"Instance {instance_id} has been commanded to start."
        except Exception as e:
            msg = f"Error starting instance: {e}"
    else:
        msg = "No stopped instance found to start. You can type 'create instance' to spawn a new one, or specify an ID (e.g., 'start instance i-12345')."
    add_log(msg)
    return {"bot_response": msg}

def stop_instance(state: State):
    ec2_client = get_boto3_client("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            reservations = ec2_client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]).get("Reservations", [])
            running_instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(running_instances) > 0:
                instance_id = running_instances[0]
                msg += f"Auto-selected running instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            manage_instance(instance_id, "stop")
            msg += f"Instance {instance_id} has been commanded to stop."
        except Exception as e:
            msg = f"Error stopping instance: {e}"
    else:
         msg = "No running instance found to stop. Please specify an instance ID or type 'create instance'."
    add_log(msg)
    return {"bot_response": msg}

def terminate_instance(state: State):
    ec2_client = get_boto3_client("ec2")
    instance_id = state.get('ID')
    msg = ""
    
    if not instance_id or instance_id == "error_id":
        try:
            reservations = ec2_client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}]).get("Reservations", [])
            instances = [inst["InstanceId"] for r in reservations for inst in r.get("Instances", [])]
            if len(instances) > 0:
                instance_id = instances[0]
                msg += f"Auto-selected instance {instance_id}. "
        except Exception as e:
            print(f"Boto3 auto-infer error: {e}")
            pass
            
    if instance_id and instance_id != "error_id":
        try:
            manage_instance(instance_id, "terminate")
            msg += f"Instance {instance_id} has been terminated."
        except Exception as e:
            msg = f"Error terminating instance: {e}"
    else:
         msg = "No instances found to terminate. Please specify an instance ID or type 'create instance'."
    add_log(msg)
    return {"bot_response": msg}

# --- VPC Operations ---
def VPC_Q(state: State):
    ec2 = get_boto3_client('ec2')
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
    
    # Manual Override Hackathon Responses
    if "savings" in user_input or "money" in user_input:
        state["bot_response"] = f"Your current AI auto-stop savings is ${total_savings:.2f}. Instances with <5% CPU are stopped automatically to save $0.45/hr."
        return state
    elif "instance" in user_input and "what" in user_input:
         state["bot_response"] = "A micro instance like t3.micro provides burstable compute performance and is cost-effective for testing."
         return state
         
    try:
        answer = llm.invoke(input=[
            SystemMessage(content="You are a helpful AWS Cloud Manager assistant. Answer clearly and concisely."),
            HumanMessage(content=state.get("input", ""))
        ])
        state["bot_response"] = answer.content
    except Exception as e:
         state["bot_response"] = f"I am unable to connect to OpenAI because the API key is missing. However, you can still type commands like 'Start instance i-xxxx' to manage your EC2 servers directly!"
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
    """Background thread that continuously checks for idle instances to stop them, saving money."""
    global total_savings
    while True:
        # Only run if AWS credentials exist
        if not aws_credentials.get("aws_access_key_id"):
            time.sleep(10)
            continue
            
        try:
            instances = list_instances()
            for inst in instances:
                if inst['status'] == 'running':
                    inst_id = inst['id']
                    cpu_val = check_cpu_utilization(inst_id) # Using the mock function
                    
                    is_idle = (cpu_val < 5)
                    
                    if is_idle:
                        msg = f"Instance {inst_id} detected as IDLE (<5% CPU). Auto-stopping to save costs..."
                        add_log(msg)
                        manage_instance(inst_id, "stop")
                        total_savings += 0.45
        except Exception as e:
            pass # Suppress output so it doesn't spam logs
            
        time.sleep(120)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the idle auto-stop background thread
    monitor_thread = threading.Thread(target=monitor_and_stop_idle_instances, daemon=True)
    monitor_thread.start()
    yield

# --- FastAPI App ---
app = FastAPI(title="AI Cloud Manager API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AWSCredentials(BaseModel):
    aws_access_key_id: str
    aws_secret_access_key: str
    region_name: str = "us-east-1"

@app.post("/api/credentials")
def set_credentials(creds: AWSCredentials):
    aws_credentials["aws_access_key_id"] = creds.aws_access_key_id
    aws_credentials["aws_secret_access_key"] = creds.aws_secret_access_key
    aws_credentials["region_name"] = creds.region_name
    
    # Test connection
    try:
        sts = get_boto3_client('sts')
        identity = sts.get_caller_identity()
        user_arn = identity.get('Arn', 'Unknown')
        add_log(f"AWS connected successfully. Identity: {user_arn}")
        return {"status": "success", "message": "Connected successfully"}
    except Exception as e:
        # Revert on failure
        aws_credentials["aws_access_key_id"] = None
        aws_credentials["aws_secret_access_key"] = None
        add_log(f"Failed to connect to AWS: {str(e)}")
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid AWS Credentials or network error.")



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

@app.post("/api/upload")
async def upload_file_endpoint(file: UploadFile = File(...), bucket_name: str = Form("dct-crud-1-20260303")):
    add_log(f"Received file upload request: {file.filename} intended for bucket: {bucket_name}")
    s3 = get_boto3_client('s3')
    
    try:
        # Read file content into memory
        file_content = await file.read()
        
        # Upload directly from memory
        s3.put_object(
            Bucket=bucket_name,
            Key=file.filename,
            Body=file_content
        )
        msg = f"Successfully uploaded {file.filename} to S3 bucket {bucket_name}."
        add_log(msg)
        return {"status": "success", "message": msg}
    except Exception as e:
        msg = f"Failed to upload file to S3: {str(e)}"
        add_log(msg)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=msg)

@app.get("/api/s3-buckets")
def get_s3_buckets():
    s3 = get_boto3_client('s3')
    try:
        response = s3.list_buckets()
        buckets = [bucket['Name'] for bucket in response.get('Buckets', [])]
        return {"status": "success", "buckets": buckets}
    except Exception as e:
        add_log(f"Error fetching S3 buckets: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Could not fetch S3 buckets")

@app.get("/api/dashboard")
def get_dashboard():
    try:
        instances = list_instances() # Use the new helper
        
        running_count = 0
        stopped_count = 0
        instances_data = []
        
        for inst in instances:
            state_name = inst["status"].lower()
            inst_id = inst["id"]
            action_text = "None"
            
            if state_name == "running":
                running_count += 1
                cpu_val = check_cpu_utilization(inst_id) # Using mocked CPU for now
                if cpu_val < 5:
                    action_text = "Monitoring (<5% CPU) - Preparing auto-stop"
                elif cpu_val > 80:
                    action_text = "High Output (>80%) - AI scaling preparing"
                else:
                    action_text = "Optimal Performance"
            elif state_name == "stopped":
                stopped_count += 1
                cpu_val = 0
                action_text = "Instance is sleeping (Cost Saved)"
            else:
                cpu_val = 0
                
            instances_data.append({
                "id": inst_id,
                "status": state_name.capitalize(),
                "cpu": cpu_val,
                "action": action_text
            })
            
        return {
            "instances": instances_data,
            "logs": list(reversed(global_logs[-20:])), # Reverse to show newest on top
            "chat": global_chat[-50:],
            "savings": total_savings,
            "totalCount": len(instances_data),
            "runningCount": running_count,
            "runRate": running_count * 0.45,
            "savingsRate": stopped_count * 0.45
        }
    except Exception as e:
        print("Error fetching dynamic data:", e)
        return {"error": str(e)}

from fastapi.responses import FileResponse
@app.get("/")
def read_root():
    return FileResponse("AICloudManager/index.html")

app.mount("/static", StaticFiles(directory="AICloudManager"), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)