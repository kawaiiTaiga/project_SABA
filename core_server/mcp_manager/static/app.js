let projectionConfig = {};
let portsData = { outports: [], inports: [] };
let routingData = { matrix: {}, connection_count: 0 };
let connections = [];
let currentDevices = [];

// ===== Tab Switching =====
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    document.querySelector(`.tab[onclick="switchTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'tools') loadToolsData();
    else if (tabName === 'matrix') loadMatrixData();
    else if (tabName === 'connections') loadConnectionsData();
    else if (tabName === 'virtual') loadVirtualToolsData();
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
        currentDevices = await devicesRes.json();

        renderDevices();
        renderGlobalSettings();
    } catch (e) {
        showAlert('Failed to load tools data: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

function renderDevices() {
    const container = document.getElementById('devices-container');
    const devices = currentDevices;
    const showOffline = document.getElementById('show-offline-devices')?.checked;

    if (!devices || devices.length === 0) {
        container.innerHTML = '<p>No registered devices.</p>';
        return;
    }

    const filteredDevices = devices.filter(d => d.online || showOffline);

    if (filteredDevices.length === 0) {
        container.innerHTML = '<p>No devices to display (offline devices are hidden).</p>';
        return;
    }

    container.innerHTML = filteredDevices.map(device => {
        const deviceId = device.device_id;
        const projection = projectionConfig.devices?.[deviceId] || {};
        const tools = device.tools || [];
        const isOffline = !device.online;

        const cardStyle = isOffline ? 'opacity: 0.6; background-color: #f0f0f0;' : '';
        const inputDisabled = isOffline ? 'disabled' : '';

        return `
            <div class="device-card" style="${cardStyle}">
                <div class="device-header" style="${isOffline ? 'background-color: #e0e0e0;' : ''}">
                    <div class="device-info">
                        <h3>${device.name || deviceId} ${isOffline ? '(OFFLINE)' : ''}</h3>
                        <div class="device-id">${deviceId}</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 15px;">
                        <span class="status-badge ${device.online ? 'status-online' : 'status-offline'}">
                            ${device.online ? 'Online' : 'Offline'}
                        </span>
                        <label><input type="checkbox" ${projection.enabled !== false ? 'checked' : ''} 
                            onchange="updateDeviceEnabled('${deviceId}', this.checked)" ${inputDisabled}> Enabled</label>
                    </div>
                </div>
                <div class="device-tools">
                    <div style="margin-bottom: 15px;">
                        <label>Device Alias: </label>
                        <input type="text" value="${projection.device_alias || ''}" 
                            onchange="updateDeviceAlias('${deviceId}', this.value)"
                            placeholder="Display name" style="width: 200px;" ${inputDisabled}>
                    </div>
                    <strong>Tools (${tools.length}):</strong>
                    <div style="margin-top: 10px;">
                        ${tools.map(tool => renderTool(deviceId, tool, projection.tools?.[tool.name] || {}, isOffline)).join('')}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderTool(deviceId, tool, toolProjection, isOffline) {
    const inputDisabled = isOffline ? 'disabled' : '';
    return `
        <div class="tool-item">
            <strong>${tool.name}</strong>
            <div style="font-size: 0.85em; color: #666;">${tool.description || 'No description'}</div>
            <div class="tool-controls">
                <label><input type="checkbox" ${toolProjection.enabled !== false ? 'checked' : ''} 
                    onchange="updateToolEnabled('${deviceId}', '${tool.name}', this.checked)" ${inputDisabled}> Enable</label>
                <input type="text" value="${toolProjection.alias || ''}" 
                    onchange="updateToolAlias('${deviceId}', '${tool.name}', this.value)"
                    placeholder="Alias" ${inputDisabled}>
                <input type="text" value="${toolProjection.description || ''}" 
                    onchange="updateToolDescription('${deviceId}', '${tool.name}', this.value)"
                    placeholder="Custom description" ${inputDisabled}>
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

async function reloadBridgeConfig() {
    try {
        showLoading(true);
        const res = await fetch('/api/bridge/reload', { method: 'POST' });
        const result = await res.json();
        if (result.ok) {
            showAlert('Configuration reloaded successfully!', 'success');
            // Refresh tools data after reload
            await loadToolsData();
        } else {
            showAlert('Reload failed: ' + result.error, 'error');
        }
    } catch (e) {
        showAlert('Reload failed: ' + e.message, 'error');
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

// ===== Virtual Tools Tab =====
let virtualToolsData = {};
let vtBindingCounter = 0;

async function loadVirtualToolsData() {
    showLoading(true);
    try {
        // Load virtual tools
        const vtRes = await fetch('/api/virtual-tools');
        virtualToolsData = await vtRes.json();

        // Also load devices for binding selection
        const devicesRes = await fetch('/api/devices');
        currentDevices = await devicesRes.json();

        renderVirtualTools();
    } catch (e) {
        showAlert('Failed to load virtual tools: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

function renderVirtualTools() {
    const container = document.getElementById('virtual-tools-list');
    const tools = Object.entries(virtualToolsData);

    if (!tools || tools.length === 0) {
        container.innerHTML = '<p>No virtual tools configured. Click \"Add Virtual Tool\" to create one.</p>';
        return;
    }

    container.innerHTML = tools.map(([name, def]) => {
        const bindings = def.bindings || [];
        const bindingsSummary = bindings.map(b => `${b.device_id}/${b.tool}`).join(', ') || 'No bindings';

        return `
            <div class="device-card">
                <div class="device-header">
                    <div class="device-info">
                        <h3>${name}</h3>
                        <div class="device-id">${def.description || 'No description'}</div>
                    </div>
                    <div class="connection-actions">
                        <button class="btn btn-primary btn-sm" onclick="editVirtualTool('${name}')">[EDIT]</button>
                        <button class="btn btn-danger btn-sm" onclick="quickDeleteVirtualTool('${name}')">[DEL]</button>
                    </div>
                </div>
                <div class="device-tools">
                    <strong>Bindings (${bindings.length}):</strong>
                    <div style="margin-top: 8px; font-size: 0.9em; color: #555;">${bindingsSummary}</div>
                </div>
            </div>
        `;
    }).join('');
}

function showAddVirtualToolModal() {
    document.getElementById('vt-modal-title').textContent = 'Add Virtual Tool';
    document.getElementById('vt-modal-name').value = '';
    document.getElementById('vt-modal-name').disabled = false;
    document.getElementById('vt-modal-description').value = '';
    document.getElementById('vt-modal-original-name').value = '';
    document.getElementById('vt-bindings-list').innerHTML = '';
    document.getElementById('vt-modal-delete-btn').style.display = 'none';
    vtBindingCounter = 0;
    document.getElementById('virtual-tool-modal').classList.add('show');
}

function editVirtualTool(name) {
    const vt = virtualToolsData[name];
    if (!vt) return;

    document.getElementById('vt-modal-title').textContent = 'Edit Virtual Tool';
    document.getElementById('vt-modal-name').value = name;
    document.getElementById('vt-modal-name').disabled = true;
    document.getElementById('vt-modal-description').value = vt.description || '';
    document.getElementById('vt-modal-original-name').value = name;
    document.getElementById('vt-modal-delete-btn').style.display = 'inline-block';

    // Render existing bindings
    const bindingsContainer = document.getElementById('vt-bindings-list');
    bindingsContainer.innerHTML = '';
    vtBindingCounter = 0;
    (vt.bindings || []).forEach(binding => {
        addVirtualToolBinding(binding.device_id, binding.tool);
    });

    document.getElementById('virtual-tool-modal').classList.add('show');
}

function closeVirtualToolModal() {
    document.getElementById('virtual-tool-modal').classList.remove('show');
}

function addVirtualToolBinding(deviceId = '', toolName = '') {
    const container = document.getElementById('vt-bindings-list');
    const id = vtBindingCounter++;

    // Build device options
    const deviceOptions = currentDevices
        .filter(d => d.online)
        .map(d => `<option value="${d.device_id}" ${d.device_id === deviceId ? 'selected' : ''}>${d.name || d.device_id}</option>`)
        .join('');

    // Build tool options (will be populated when device changes)
    const toolOptions = deviceId ? buildToolOptions(deviceId, toolName) : '<option value="">-- Select device first --</option>';

    const bindingHtml = `
        <div class="form-row" id="vt-binding-${id}" style="margin-bottom: 10px; align-items: center;">
            <div class="form-group" style="flex: 1;">
                <select id="vt-binding-device-${id}" onchange="updateToolOptions(${id})">
                    <option value="">-- Select Device --</option>
                    ${deviceOptions}
                </select>
            </div>
            <div class="form-group" style="flex: 1;">
                <select id="vt-binding-tool-${id}">
                    ${toolOptions}
                </select>
            </div>
            <button class="btn btn-danger btn-sm" onclick="removeVirtualToolBinding(${id})" style="padding: 5px 10px;">[X]</button>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', bindingHtml);
}

function buildToolOptions(deviceId, selectedTool = '') {
    const device = currentDevices.find(d => d.device_id === deviceId);
    if (!device || !device.tools) return '<option value="">-- No tools --</option>';

    return device.tools.map(t =>
        `<option value="${t.name}" ${t.name === selectedTool ? 'selected' : ''}>${t.name}</option>`
    ).join('');
}

function updateToolOptions(id) {
    const deviceId = document.getElementById(`vt-binding-device-${id}`).value;
    const toolSelect = document.getElementById(`vt-binding-tool-${id}`);
    toolSelect.innerHTML = deviceId ? buildToolOptions(deviceId) : '<option value="">-- Select device first --</option>';
}

function removeVirtualToolBinding(id) {
    const el = document.getElementById(`vt-binding-${id}`);
    if (el) el.remove();
}

function collectBindings() {
    const bindings = [];
    const bindingRows = document.querySelectorAll('[id^="vt-binding-"]');

    bindingRows.forEach(row => {
        const id = row.id.replace('vt-binding-', '');
        const deviceId = document.getElementById(`vt-binding-device-${id}`)?.value;
        const toolName = document.getElementById(`vt-binding-tool-${id}`)?.value;

        if (deviceId && toolName) {
            bindings.push({ device_id: deviceId, tool: toolName });
        }
    });

    return bindings;
}

async function saveVirtualTool() {
    const originalName = document.getElementById('vt-modal-original-name').value;
    const name = document.getElementById('vt-modal-name').value.trim();
    const description = document.getElementById('vt-modal-description').value.trim();
    const bindings = collectBindings();

    if (!name) {
        showAlert('Name is required', 'error');
        return;
    }

    try {
        showLoading(true);

        const data = { name, description, bindings };

        if (originalName) {
            // Update
            await fetch(`/api/virtual-tools/${originalName}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            showAlert('Virtual tool updated', 'success');
        } else {
            // Create
            await fetch('/api/virtual-tools', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            showAlert('Virtual tool created', 'success');
        }

        closeVirtualToolModal();
        loadVirtualToolsData();
    } catch (e) {
        showAlert('Save failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function deleteVirtualTool() {
    const name = document.getElementById('vt-modal-original-name').value;
    if (!name || !confirm(`Delete virtual tool "${name}"?`)) return;

    try {
        showLoading(true);
        await fetch(`/api/virtual-tools/${name}`, { method: 'DELETE' });
        showAlert('Virtual tool deleted', 'success');
        closeVirtualToolModal();
        loadVirtualToolsData();
    } catch (e) {
        showAlert('Delete failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function quickDeleteVirtualTool(name) {
    if (!confirm(`Delete virtual tool "${name}"?`)) return;

    try {
        showLoading(true);
        await fetch(`/api/virtual-tools/${name}`, { method: 'DELETE' });
        showAlert('Virtual tool deleted', 'success');
        loadVirtualToolsData();
    } catch (e) {
        showAlert('Delete failed: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ===== Init =====
window.onload = function () {
    checkStatus();
    setInterval(checkStatus, 10000);
    loadToolsData();
};
