// Simulated data fetching (since we don't have a real AWS API Gateway yet)
// This structure mimics what the Lambda + API Gateway would return.

// Global Chart Instance
let cpuChartInstance = null;
let totalSavings = 3.20;

// Utility functions
const formatTime = (date) => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
};

// Fetch real data from the local Python FastAPI server
const fetchRealData = async () => {
    try {
        const response = await fetch(`/api/dashboard`);
        if (!response.ok) throw new Error("API Offline or returning error.");
        const data = await response.json();
        return data;
    } catch (err) {
        console.error("Failed fetching live AWS data, ensure the Python backend is running on port 5000.", err);
        return null; // Don't crash UI, just wait for next update
    }
};


// Render Table
const renderTable = (instances) => {
    const tbody = document.getElementById('instances-body');
    tbody.innerHTML = '';

    instances.forEach(inst => {
        const tr = document.createElement('tr');

        // Status badge class
        const statusClass = `status-${inst.status.toLowerCase()}`;

        // CPU bar
        const cpuColor = inst.cpu > 80 ? 'var(--accent-red)' : (inst.cpu > 50 ? 'var(--accent-yellow)' : (inst.cpu < 5 ? '#8b5cf6' : 'var(--accent-green)'));
        const cpuHtml = (inst.status === 'Running' || inst.status === 'Idle')
            ? `<div style="display:flex; align-items:center; gap:10px;">
                 <div style="width: 50px; background: rgba(255,255,255,0.1); border-radius: 4px; height: 6px; overflow: hidden;">
                   <div style="width: ${inst.cpu}%; background: ${cpuColor}; height: 100%;"></div>
                 </div>
                 <span>${inst.cpu}%</span>
               </div>`
            : '<span style="color: var(--text-secondary)">N/A</span>';

        tr.innerHTML = `
            <td style="font-family: monospace; color: var(--accent-blue)">${inst.id}</td>
            <td><span class="status-badge ${statusClass}">${inst.status}</span></td>
            <td>${cpuHtml}</td>
            <td>${inst.action}</td>
        `;
        tbody.appendChild(tr);
    });
};

// Render Logs
const renderLogs = (logs) => {
    const logsContainer = document.getElementById('ai-logs');
    logsContainer.innerHTML = '';

    logs.forEach(logText => {
        // Extract time if it's bracketed
        const timeMatch = logText.match(/^\[(.*?)\]\s*(.*)$/);
        let timeHTML = '';
        let contentHTML = logText;

        if (timeMatch) {
            timeHTML = `<span class="log-time">${timeMatch[1]}</span>`;
            contentHTML = timeMatch[2];
        }

        const div = document.createElement('div');
        div.className = 'log-item';
        div.innerHTML = `${timeHTML}<span>${contentHTML}</span>`;
        logsContainer.appendChild(div);
    });
};


// Render Chat
const renderChat = (chatArray) => {
    const chatContainer = document.getElementById('chat-history');
    chatContainer.innerHTML = '';

    chatArray.forEach(msg => {
        const div = document.createElement('div');
        div.className = `chat-bubble chat-${msg.sender}`;
        div.textContent = msg.text;
        chatContainer.appendChild(div);
    });

    // Auto scroll chat to bottom
    chatContainer.scrollTop = chatContainer.scrollHeight;
};

// Render Chart
const renderChart = (instances) => {
    const ctx = document.getElementById('cpuChart').getContext('2d');

    // Categorize CPU ranges for running and idle instances
    let idle = 0, optimal = 0, high = 0;
    instances.forEach(i => {
        if (i.status === 'Running' || i.status === 'Idle') {
            if (i.cpu < 5) idle++;
            else if (i.cpu <= 80) optimal++;
            else high++;
        }
    });

    const data = {
        labels: ['Idle (<5%) - Stopping Soon', 'Optimal (5-80%)', 'High Load (>80%)'],
        datasets: [{
            data: [idle, optimal, high],
            backgroundColor: [
                '#8b5cf6', // purple for idle
                '#10b981', // green
                '#ef4444'  // red
            ],
            borderWidth: 0,
            hoverOffset: 4
        }]
    };

    if (cpuChartInstance) {
        cpuChartInstance.data = data;
        cpuChartInstance.update();
    } else {
        cpuChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#9ca3af',
                            font: { family: 'Inter' }
                        }
                    }
                },
                cutout: '70%',
                animation: {
                    animateScale: true,
                    animateRotate: true
                }
            }
        });
    }
};

// Render CPU Monitors
const renderCpuMonitors = (instances) => {
    const container = document.getElementById('cpu-monitors-container');
    if (!container) return;
    container.innerHTML = '';

    instances.forEach(inst => {
        const div = document.createElement('div');
        div.className = 'monitor-card';

        const cpuColor = inst.cpu > 80 ? 'var(--accent-red)' : (inst.cpu > 50 ? 'var(--accent-yellow)' : (inst.cpu < 5 ? '#8b5cf6' : 'var(--accent-green)'));
        const cpuText = (inst.status === 'Running' || inst.status === 'Idle') ? `${inst.cpu}% CPU` : 'OFF';
        const displayWidth = (inst.status === 'Running' || inst.status === 'Idle') ? inst.cpu : 0;

        div.innerHTML = `
            <h4>${inst.id}</h4>
            <span class="status-text">Status: ${inst.status}</span>
            <div class="progress-bar-container">
                <div class="progress-fill" style="width: ${displayWidth}%; background-color: ${cpuColor};"></div>
            </div>
            <span class="cpu-text" style="color: ${cpuColor}">${cpuText}</span>
        `;
        container.appendChild(div);
    });
};

// Main Fetch and Update fn
const updateDashboard = async () => {
    const data = await fetchRealData();
    if (!data) return; // Wait for backend

    // Update Top Stats
    document.getElementById('stat-total').innerText = data.totalCount || 0;
    document.getElementById('stat-running').innerText = data.runningCount || 0;

    // Update Billing Stats
    if (document.getElementById('stat-runrate')) {
        document.getElementById('stat-runrate').innerText = `$${(data.runRate || 0).toFixed(2)} / hr`;
        document.getElementById('stat-saverate').innerText = `$${(data.savingsRate || 0).toFixed(2)} / hr`;
        document.getElementById('stat-savings-total').innerText = `$${parseFloat(data.savings || 0).toFixed(2)}`;
    } else {
        // Fallback for old layout
        document.getElementById('stat-savings').innerText = `$${parseFloat(data.savings || 0).toFixed(2)}`;
    }

    // Render Components
    if (data.instances) {
        renderTable(data.instances);
        renderChart(data.instances);
        renderCpuMonitors(data.instances);
    }
    if (data.logs) renderLogs(data.logs);
    if (data.chat) renderChat(data.chat);
};

// User Chat Interaction Integration
const sendChatMessage = async (msg) => {
    const chatContainer = document.getElementById('chat-history');
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send-btn');

    // Disable input while processing
    if (input) input.disabled = true;
    if (btn) btn.disabled = true;

    // 1. Instantly show user message locally
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-bubble chat-user';
    userDiv.textContent = msg;
    chatContainer.appendChild(userDiv);

    // 2. Show typing indicator locally
    const typingDiv = document.createElement('div');
    typingDiv.className = 'chat-bubble chat-bot typing-indicator';
    typingDiv.id = 'temp-typing-indicator';
    typingDiv.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    `;
    chatContainer.appendChild(typingDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const response = await fetch(`/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        if (response.ok) {
            await updateDashboard(); // update UI to reflect the formal command logs and actual bot response
        }
    } catch (e) {
        console.error("Error sending chat:", e);
        const errDiv = document.createElement('div');
        errDiv.className = 'chat-bubble chat-bot';
        errDiv.textContent = "Error: Cannot connect to AI backend.";
        chatContainer.appendChild(errDiv);
    } finally {
        if (input) {
            input.value = '';
            input.disabled = false;
            input.focus();
        }
        if (btn) btn.disabled = false;

        // Remove typing indicator if it somehow survived the updateDashboard overwrite
        const temp = document.getElementById('temp-typing-indicator');
        if (temp) temp.remove();
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
};

const setupChatListeners = () => {
    const btn = document.getElementById('chat-send-btn');
    const input = document.getElementById('chat-input');

    const submitChat = () => {
        const text = input.value.trim();
        if (text) {
            sendChatMessage(text);
        }
    };

    if (btn) {
        btn.addEventListener('click', submitChat);
    }

    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                submitChat();
            }
        });
    }
};

// Fetch Available S3 Buckets
const fetchS3Buckets = async () => {
    const bucketSelect = document.getElementById('s3-bucket-select');
    if (!bucketSelect) return;

    try {
        const response = await fetch(`/api/s3-buckets`);
        if (response.ok) {
            const data = await response.json();
            bucketSelect.innerHTML = '';

            if (data.buckets && data.buckets.length > 0) {
                data.buckets.forEach(bucket => {
                    const option = document.createElement('option');
                    option.value = bucket;
                    option.textContent = bucket;
                    bucketSelect.appendChild(option);
                });
            } else {
                bucketSelect.innerHTML = '<option value="">No buckets found</option>';
            }
        } else {
            bucketSelect.innerHTML = '<option value="">Error fetching buckets</option>';
        }
    } catch (err) {
        console.error("Failed fetching S3 buckets:", err);
        bucketSelect.innerHTML = '<option value="">API Offline</option>';
    }
};

// S3 File Upload Logic
const setupS3Uploader = () => {
    const uploadBtn = document.getElementById('s3-upload-btn');
    const fileInput = document.getElementById('s3-file-input');
    const statusDiv = document.getElementById('s3-upload-status');
    const bucketSelect = document.getElementById('s3-bucket-select');

    if (uploadBtn && fileInput && statusDiv && bucketSelect) {
        uploadBtn.addEventListener('click', async () => {
            const file = fileInput.files[0];
            const selectedBucket = bucketSelect.value;

            if (!selectedBucket) {
                statusDiv.textContent = "Please select a target bucket.";
                statusDiv.style.color = "var(--accent-yellow)";
                return;
            }

            if (!file) {
                statusDiv.textContent = "Please select a file first.";
                statusDiv.style.color = "var(--accent-yellow)";
                return;
            }

            uploadBtn.disabled = true;
            statusDiv.textContent = `Uploading ${file.name} to ${selectedBucket}...`;
            statusDiv.style.color = "var(--text-secondary)";

            const formData = new FormData();
            formData.append("file", file);
            formData.append("bucket_name", selectedBucket);

            try {
                const response = await fetch(`/api/upload`, {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const result = await response.json();
                    statusDiv.textContent = result.message || "Upload successful!";
                    statusDiv.style.color = "var(--accent-green)";
                    fileInput.value = ""; // Clear input
                    await updateDashboard(); // Refresh logs
                } else {
                    const err = await response.json();
                    statusDiv.textContent = err.detail || "Upload failed.";
                    statusDiv.style.color = "var(--accent-red)";
                }
            } catch (error) {
                console.error("Upload error:", error);
                statusDiv.textContent = "Network error or API offline.";
                statusDiv.style.color = "var(--accent-red)";
            } finally {
                uploadBtn.disabled = false;
            }
        });
    }
};

// AWS Credentials Logic
let isAwsConfigured = false;

const setupAwsConfig = () => {
    const connectBtn = document.getElementById('aws-connect-btn');
    const accessKeyInput = document.getElementById('aws-access-key');
    const secretKeyInput = document.getElementById('aws-secret-key');
    const regionInput = document.getElementById('aws-region');
    const statusDiv = document.getElementById('aws-config-status');
    const configContainer = document.getElementById('aws-config-container');
    const mainDashboard = document.getElementById('main-dashboard-container');

    if (connectBtn) {
        connectBtn.addEventListener('click', async () => {
            const accessKey = accessKeyInput.value.trim();
            const secretKey = secretKeyInput.value.trim();
            const region = regionInput.value.trim() || 'us-east-1';

            if (!accessKey || !secretKey) {
                statusDiv.textContent = "Please enter both Access Key and Secret Key.";
                statusDiv.style.color = "var(--accent-yellow)";
                return;
            }

            connectBtn.disabled = true;
            statusDiv.textContent = "Connecting to AWS...";
            statusDiv.style.color = "var(--text-secondary)";

            try {
                const response = await fetch(`/api/credentials`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        aws_access_key_id: accessKey,
                        aws_secret_access_key: secretKey,
                        region_name: region
                    })
                });

                if (response.ok) {
                    const result = await response.json();
                    statusDiv.textContent = result.message || "Connected successfully!";
                    statusDiv.style.color = "var(--accent-green)";

                    isAwsConfigured = true;

                    // Hide Config, Show Dashboard
                    setTimeout(() => {
                        configContainer.style.display = 'none';
                        mainDashboard.style.display = 'grid'; // .dashboard-container uses grid usually, or block

                        // Initial Data Fetch
                        fetchS3Buckets();
                        updateDashboard();
                    }, 1000);

                } else {
                    const err = await response.json();
                    statusDiv.textContent = err.detail || "Failed to connect to AWS.";
                    statusDiv.style.color = "var(--accent-red)";
                    connectBtn.disabled = false;
                }
            } catch (error) {
                console.error("Credentials error:", error);
                statusDiv.textContent = "Network error or API offline.";
                statusDiv.style.color = "var(--accent-red)";
                connectBtn.disabled = false;
            }
        });
    }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupAwsConfig();
    setupChatListeners();
    setupS3Uploader();

    // Auto refresh every 10 seconds (only if configured)
    setInterval(() => {
        if (!isAwsConfigured) return;

        console.log("Refreshing data...");
        // Only auto refresh if we are NOT actively waiting for a chat response
        const isTyping = document.getElementById('temp-typing-indicator');
        if (!isTyping) {
            updateDashboard();
        }
    }, 10000);
});
