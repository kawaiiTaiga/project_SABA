let projectionConfig = {};
let portsData = { outports: [], inports: [] };
let routingData = { matrix: {}, connection_count: 0 };
let connections = [];

// ===== Tab Switching =====
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    document.querySelector(`.tab[onclick="switchTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'tools') loadToolsData();
    else if (tabName === 'matrix') loadMatrixData();
    else if (tabName === 'connections') loadConnectionsData();
}

// ===== Status Check =====
async function checkStatus() {
    try {
        const bridgeRes = await fetch('/api/bridge/health');
        const bridgeData = await bridgeRes.json();
        const bridgeEl = document.getElementById('bridge-status');
        bridgeEl.textContent = `Bridge: ${bridgeData.healthy ? 'Online' : 'Offline'}`;
        bridgeEl.className = `status-badge ${bridgeData.healthy ? 'status-online' : 'status-offline'}`;

        const dockerRes = await fetch('/api/docker/status');
        const dockerData = await dockerRes.json();
        const dockerEl = document.getElementById('docker-status');
        dockerEl.textContent = `Docker: ${dockerData.running ? 'Running' : 'Stopped'}`;
        dockerEl.className = `status-badge ${dockerData.running ? 'status-online' : 'status-offline'}`;
    } catch (e) {
        console.error('Status check failed:', e);
    }
}

// ===== Tools Tab =====
async function loadToolsData() {
    showLoading(true);
    try {
        const configRes = await fetch('/api/projection/config');
        projectionConfig = await configRes.json();

        const devicesRes = await fetch('/api/devices');
        const devices = await devicesRes.json();

        renderDevices(devices);
        renderGlobalSettings();
    } catch (e) {
        showAlert('Failed to load tools data: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

function renderDevices(devices) {
    const container = document.getElementById('devices-container');
    if (!devices || devices.length === 0) {
        container.innerHTML = '<p>No registered devices.</p>';
        return;
    }

    container.innerHTML = devices.map(device => {
        const deviceId = device.device_id;
        const projection = projectionConfig.devices?.[deviceId] || {};
        const tools = device.tools || [];

        return `
            <div class="device-card">
                <div class="device-header">
                    <div class="device-info">
                        <h3>${device.name || deviceId}</h3>
                        <div class="device-id">${deviceId}</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 15px;">
                        <span class="status-badge ${device.online ? 'status-online' : 'status-offline'}">
                            ${device.online ? 'Online' : 'Offline'}
                        </span>
                        <label><input type="checkbox" ${projection.enabled !== false ? 'checked' : ''} 
                            onchange="updateDeviceEnabled('${deviceId}', this.checked)"> Enabled</label>
                    </div>
                </div>
                <div class="device-tools">
                    <div style="margin-bottom: 15px;">
                        <label>Device Alias: </label>
                        <input type="text" value="${projection.device_alias || ''}" 
                            onchange="updateDeviceAlias('${deviceId}', this.value)"
                            placeholder="Display name" style="width: 200px;">
                    </div>
                    <strong>Tools (${tools.length}):</strong>
                    <div style="margin-top: 10px;">
                        ${tools.map(tool => renderTool(deviceId, tool, projection.tools?.[tool.name] || {})).join('')}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderTool(deviceId, tool, toolProjection) {
    return `
        <div class="tool-item">
            <strong>${tool.name}</strong>
            <div style="font-size: 0.85em; color: #666;">${tool.description || 'No description'}</div>
            <div class="tool-controls">
                <label><input type="checkbox" ${toolProjection.enabled !== false ? 'checked' : ''} 
                    onchange="updateToolEnabled('${deviceId}', '${tool.name}', this.checked)"> Enable</label>
                <input type="text" value="${toolProjection.alias || ''}" 
                    onchange="updateToolAlias('${deviceId}', '${tool.name}', this.value)"
                    placeholder="Alias">
                <input type="text" value="${toolProjection.description || ''}" 
                    onchange="updateToolDescription('${deviceId}', '${tool.name}', this.value)"
                    placeholder="Custom description">
            </div>
        </div>
    `;
}

function renderGlobalSettings() {
    document.getElementById('auto-enable-devices').checked = projectionConfig.global?.auto_enable_new_devices !== false;
    document.getElementById('auto-enable-tools').checked = projectionConfig.global?.auto_enable_new_tools !== false;
}

function ensureDeviceConfig(deviceId) {
    if (!projectionConfig.devices) projectionConfig.devices = {};
    if (!projectionConfig.devices[deviceId]) {
        projectionConfig.devices[deviceId] = { enabled: true, device_alias: null, tools: {} };
    }
}

function ensureToolConfig(deviceId, toolName) {
    ensureDeviceConfig(deviceId);
    if (!projectionConfig.devices[deviceId].tools) projectionConfig.devices[deviceId].tools = {};
    if (!projectionConfig.devices[deviceId].tools[toolName]) {
        projectionConfig.devices[deviceId].tools[toolName] = { enabled: true, alias: null, description: null };
    }
}

function updateDeviceEnabled(deviceId, enabled) { ensureDeviceConfig(deviceId); projectionConfig.devices[deviceId].enabled = enabled; }
function updateDeviceAlias(deviceId, alias) { ensureDeviceConfig(deviceId); projectionConfig.devices[deviceId].device_alias = alias || null; }
function updateToolEnabled(deviceId, toolName, enabled) { ensureToolConfig(deviceId, toolName); projectionConfig.devices[deviceId].tools[toolName].enabled = enabled; }
function updateToolAlias(deviceId, toolName, alias) { ensureToolConfig(deviceId, toolName); projectionConfig.devices[deviceId].tools[toolName].alias = alias || null; }
function updateToolDescription(deviceId, toolName, desc) { ensureToolConfig(deviceId, toolName); projectionConfig.devices[deviceId].tools[toolName].description = desc || null; }

async function saveProjectionConfig() {
    projectionConfig.global = {
        auto_enable_new_devices: document.getElementById('auto-enable-devices').checked,
        auto_enable_new_tools: document.getElementById('auto-enable-tools').checked
    };

    try {
        showLoading(true);
        const res = await fetch('/api/projection/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(projectionConfig)
        });
        const result = await res.json();
        if (res.ok) showAlert('Configuration saved!', 'success');
        else showAlert('Save failed: ' + result.message, 'error');
    } catch (e) {
        showAlert('Save failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function restartBridge() {
    if (!confirm('Are you sure you want to restart the Bridge container?')) return;

    try {
        showLoading(true);
        const res = await fetch('/api/docker/restart', { method: 'POST' });
        const result = await res.json();
        if (result.ok) showAlert('Bridge container restarted!', 'success');
        else showAlert('Restart failed: ' + result.error, 'error');
    } catch (e) {
        showAlert('Restart failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ===== Matrix Tab =====
async function loadMatrixData() {
    showLoading(true);
    try {
        const portsRes = await fetch('/api/ports');
        portsData = await portsRes.json();

        const routingRes = await fetch('/api/routing');
        routingData = await routingRes.json();

        renderMatrix();
    } catch (e) {
        showAlert('Failed to load matrix data: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

function renderMatrix() {
    const outports = portsData.outports || [];
    const inports = portsData.inports || [];
    const matrix = routingData.matrix || {};

    document.getElementById('stat-outports').textContent = outports.length;
    document.getElementById('stat-inports').textContent = inports.length;
    document.getElementById('stat-connections').textContent = routingData.connection_count || 0;

    if (outports.length === 0 || inports.length === 0) {
        document.getElementById('routing-matrix').innerHTML = '<tr><td colspan="99">No ports available. Make sure devices have announced their ports.</td></tr>';
        return;
    }

    let html = '<thead><tr><th>OutPort \\\\ InPort</th>';
    inports.forEach(inp => {
        html += `<th><span class="port-badge port-in">${inp.port_id}</span></th>`;
    });
    html += '</tr></thead><tbody>';

    outports.forEach(outp => {
        html += `<tr><td><span class="port-badge port-out">${outp.port_id}</span></td>`;
        inports.forEach(inp => {
            const cell = matrix[outp.port_id]?.[inp.port_id] || { connected: false };
            const connected = cell.connected;
            const enabled = cell.enabled !== false;

            let cellClass = 'matrix-cell';
            if (connected && enabled) cellClass += ' connected';
            else if (connected && !enabled) cellClass += ' disabled';

            html += `<td class="${cellClass}" onclick="toggleConnection('${outp.port_id}', '${inp.port_id}', ${connected})">
                <div class="connection-dot ${connected ? 'dot-connected' : 'dot-empty'}"></div>
            </td>`;
        });
        html += '</tr>';
    });
    html += '</tbody>';

    document.getElementById('routing-matrix').innerHTML = html;
}

async function toggleConnection(source, target, isConnected) {
    showLoading(true);
    try {
        if (isConnected) {
            await fetch('/api/routing/disconnect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source, target })
            });
            showAlert(`Disconnected: ${source} → ${target}`, 'success');
        } else {
            await fetch('/api/routing/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source, target, transform: {}, description: '' })
            });
            showAlert(`Connected: ${source} → ${target}`, 'success');
        }
        await loadMatrixData();
    } catch (e) {
        showAlert('Operation failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ===== Connections Tab =====
async function loadConnectionsData() {
    showLoading(true);
    try {
        const portsRes = await fetch('/api/ports');
        portsData = await portsRes.json();

        const connRes = await fetch('/api/routing/connections');
        connections = await connRes.json();

        renderConnections();
    } catch (e) {
        showAlert('Failed to load connections: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

function renderConnections() {
    const container = document.getElementById('connections-list');

    if (!connections || connections.length === 0) {
        container.innerHTML = '<p>No connections configured. Click "Add Connection" to create one.</p>';
        return;
    }

    container.innerHTML = connections.map(conn => {
        const transformStr = Object.keys(conn.transform || {}).length > 0
            ? JSON.stringify(conn.transform)
            : 'none';
        const statusIcon = conn.enabled ? '[ON]' : '[OFF]';

        return `
            <div class="connection-item">
                <div class="connection-info">
                    <div class="connection-path">
                        ${statusIcon} <span class="port-badge port-out">${conn.source}</span> 
                        → <span class="port-badge port-in">${conn.target}</span>
                    </div>
                    <div class="connection-transform">Transform: ${transformStr}</div>
                    ${conn.description ? `<div style="font-size: 0.85em; color: #888;">${conn.description}</div>` : ''}
                </div>
                <div class="connection-actions">
                    <button class="btn btn-primary btn-sm" onclick="editConnection('${conn.id}')">[EDIT]</button>
                    <button class="btn btn-danger btn-sm" onclick="quickDelete('${conn.id}')">[DEL]</button>
                </div>
            </div>
        `;
    }).join('');
}

async function quickDelete(connectionId) {
    if (!confirm('Delete this connection?')) return;
    try {
        showLoading(true);
        await fetch('/api/routing/disconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ connection_id: connectionId })
        });
        showAlert('Connection deleted', 'success');
        loadConnectionsData();
    } catch (e) {
        showAlert('Delete failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ===== Modal =====
function showAddConnectionModal() {
    document.getElementById('modal-title').textContent = 'Add Connection';
    document.getElementById('modal-connection-id').value = '';
    document.getElementById('modal-source').innerHTML = portsData.outports.map(p => `<option value="${p.port_id}">${p.port_id}</option>`).join('');
    document.getElementById('modal-target').innerHTML = portsData.inports.map(p => `<option value="${p.port_id}">${p.port_id}</option>`).join('');
    document.getElementById('modal-scale').value = '';
    document.getElementById('modal-offset').value = '';
    document.getElementById('modal-threshold').value = '';
    document.getElementById('modal-enabled').value = 'true';
    document.getElementById('modal-description').value = '';
    document.getElementById('modal-delete-btn').style.display = 'none';
    document.getElementById('connection-modal').classList.add('show');
}

function editConnection(connectionId) {
    const conn = connections.find(c => c.id === connectionId);
    if (!conn) return;

    document.getElementById('modal-title').textContent = 'Edit Connection';
    document.getElementById('modal-connection-id').value = connectionId;
    document.getElementById('modal-source').innerHTML = portsData.outports.map(p => `<option value="${p.port_id}" ${p.port_id === conn.source ? 'selected' : ''}>${p.port_id}</option>`).join('');
    document.getElementById('modal-target').innerHTML = portsData.inports.map(p => `<option value="${p.port_id}" ${p.port_id === conn.target ? 'selected' : ''}>${p.port_id}</option>`).join('');
    document.getElementById('modal-scale').value = conn.transform?.scale || '';
    document.getElementById('modal-offset').value = conn.transform?.offset || '';
    document.getElementById('modal-threshold').value = conn.transform?.threshold || '';
    document.getElementById('modal-enabled').value = conn.enabled !== false ? 'true' : 'false';
    document.getElementById('modal-description').value = conn.description || '';
    document.getElementById('modal-delete-btn').style.display = 'inline-block';
    document.getElementById('connection-modal').classList.add('show');
}

function closeModal() {
    document.getElementById('connection-modal').classList.remove('show');
}

async function saveConnection() {
    const id = document.getElementById('modal-connection-id').value;
    const source = document.getElementById('modal-source').value;
    const target = document.getElementById('modal-target').value;
    const scale = document.getElementById('modal-scale').value;
    const offset = document.getElementById('modal-offset').value;
    const threshold = document.getElementById('modal-threshold').value;
    const enabled = document.getElementById('modal-enabled').value === 'true';
    const description = document.getElementById('modal-description').value;

    const transform = {};
    if (scale) transform.scale = parseFloat(scale);
    if (offset) transform.offset = parseFloat(offset);
    if (threshold) {
        transform.threshold = parseFloat(threshold);
        transform.threshold_mode = 'above';
    }

    try {
        showLoading(true);
        if (id) {
            // Update
            await fetch(`/api/routing/connection/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source, target, transform, enabled, description })
            });
            showAlert('Connection updated', 'success');
        } else {
            // Create
            await fetch('/api/routing/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source, target, transform, enabled, description })
            });
            showAlert('Connection created', 'success');
        }
        closeModal();
        loadConnectionsData();
    } catch (e) {
        showAlert('Save failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function deleteConnection() {
    const id = document.getElementById('modal-connection-id').value;
    if (!id || !confirm('Delete this connection?')) return;

    try {
        showLoading(true);
        await fetch('/api/routing/disconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ connection_id: id })
        });
        showAlert('Connection deleted', 'success');
        closeModal();
        loadConnectionsData();
    } catch (e) {
        showAlert('Delete failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ===== UI Helpers =====
function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'block' : 'none';
}

function showAlert(msg, type) {
    const el = document.getElementById('alert');
    el.textContent = msg;
    el.className = `alert alert-${type}`;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 3000);
}

// ===== Init =====
window.onload = function () {
    checkStatus();
    setInterval(checkStatus, 10000);
    loadToolsData();
};
