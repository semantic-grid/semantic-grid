"""HTML UI for the OTel console."""


def get_html() -> str:
    """Return the single-page HTML application."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>dbmeta console</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }

        header {
            background: #16213e;
            padding: 1rem 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #0f3460;
        }

        header h1 {
            font-size: 1.25rem;
            font-weight: 500;
            color: #e94560;
        }

        header .controls {
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        header button {
            background: #0f3460;
            color: #eee;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.875rem;
        }

        header button:hover {
            background: #1a4980;
        }

        .status {
            font-size: 0.75rem;
            color: #888;
        }

        .status.connected { color: #4ade80; }
        .status.error { color: #f87171; }

        main {
            padding: 1rem 2rem;
        }

        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: #666;
        }

        .empty-state h2 {
            font-size: 1.5rem;
            margin-bottom: 1rem;
            color: #888;
        }

        .trace-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .trace {
            background: #16213e;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #0f3460;
        }

        .trace-header {
            padding: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            border-bottom: 1px solid #0f3460;
        }

        .trace-header:hover {
            background: #1a2744;
        }

        .trace-title {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .trace-name {
            font-weight: 500;
            color: #e94560;
        }

        .trace-meta {
            font-size: 0.75rem;
            color: #888;
            display: flex;
            gap: 1rem;
        }

        .trace-duration {
            color: #4ade80;
            font-family: monospace;
        }

        .trace-spans {
            padding: 0.5rem 1rem 1rem;
            display: none;
        }

        .trace.expanded .trace-spans {
            display: block;
        }

        .timeline {
            position: relative;
            padding: 0.5rem 0;
        }

        .span-row {
            display: flex;
            align-items: center;
            padding: 0.25rem 0;
            font-size: 0.8125rem;
        }

        .span-label {
            width: 200px;
            flex-shrink: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            padding-right: 1rem;
            color: #ccc;
        }

        .span-bar-container {
            flex: 1;
            height: 20px;
            position: relative;
            background: #0f3460;
            border-radius: 2px;
        }

        .span-bar {
            position: absolute;
            height: 100%;
            background: linear-gradient(90deg, #e94560, #f472b6);
            border-radius: 2px;
            min-width: 2px;
        }

        .span-bar.error {
            background: linear-gradient(90deg, #dc2626, #f87171);
        }

        .span-duration {
            width: 80px;
            flex-shrink: 0;
            text-align: right;
            font-family: monospace;
            font-size: 0.75rem;
            color: #888;
            padding-left: 0.5rem;
        }

        .span-details {
            margin-top: 0.5rem;
            padding: 0.5rem;
            background: #0f3460;
            border-radius: 4px;
            font-size: 0.75rem;
            display: none;
        }

        .span-row.selected .span-details {
            display: block;
        }

        .attr-table {
            width: 100%;
            border-collapse: collapse;
        }

        .attr-table td {
            padding: 0.25rem 0.5rem;
            border-bottom: 1px solid #1a2744;
        }

        .attr-table td:first-child {
            color: #888;
            width: 150px;
        }

        .attr-table td:last-child {
            color: #4ade80;
            font-family: monospace;
            word-break: break-all;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .loading {
            animation: pulse 1.5s infinite;
        }
    </style>
</head>
<body>
    <header>
        <h1>dbmeta console</h1>
        <div class="controls">
            <span class="status" id="status">Connecting...</span>
            <button onclick="clearTraces()">Clear</button>
            <button onclick="refresh()">Refresh</button>
        </div>
    </header>

    <main>
        <div id="content" class="loading">
            <div class="empty-state">
                <h2>Loading...</h2>
            </div>
        </div>
    </main>

    <script>
        let traces = [];
        let autoRefresh = true;
        let refreshInterval = null;

        async function fetchTraces() {
            try {
                const res = await fetch('/api/traces');
                const data = await res.json();
                traces = data.traces || [];
                updateStatus('connected');
                render();
            } catch (err) {
                updateStatus('error');
                console.error('Failed to fetch traces:', err);
            }
        }

        function updateStatus(state) {
            const el = document.getElementById('status');
            el.className = 'status ' + state;
            el.textContent = state === 'connected' ? 'Connected' :
                             state === 'error' ? 'Connection error' : 'Connecting...';
        }

        function render() {
            const content = document.getElementById('content');
            content.classList.remove('loading');

            if (traces.length === 0) {
                content.innerHTML = `
                    <div class="empty-state">
                        <h2>No traces yet</h2>
                        <p>Traces will appear here when the MCP server handles requests.</p>
                    </div>
                `;
                return;
            }

            content.innerHTML = `
                <div class="trace-list">
                    ${traces.map(renderTrace).join('')}
                </div>
            `;
        }

        function renderTrace(trace) {
            const time = new Date(trace.start_time * 1000).toLocaleTimeString();
            const duration = formatDuration(trace.duration_ms);

            return `
                <div class="trace" id="trace-${trace.trace_id}">
                    <div class="trace-header" onclick="toggleTrace('${trace.trace_id}')">
                        <div class="trace-title">
                            <span class="trace-name">${escapeHtml(trace.root_span || 'Unknown')}</span>
                        </div>
                        <div class="trace-meta">
                            <span>${trace.span_count} spans</span>
                            <span class="trace-duration">${duration}</span>
                            <span>${time}</span>
                        </div>
                    </div>
                    <div class="trace-spans">
                        <div class="timeline">
                            ${trace.spans.map(span => renderSpan(span, trace)).join('')}
                        </div>
                    </div>
                </div>
            `;
        }

        function renderSpan(span, trace) {
            const traceStart = trace.start_time;
            const traceDuration = trace.duration_ms || 1;

            const spanStart = span.start_time - traceStart;
            const spanDuration = span.duration_ms || 0;

            const left = (spanStart * 1000 / traceDuration) * 100;
            const width = Math.max((spanDuration / traceDuration) * 100, 0.5);

            const statusClass = span.status === 'error' ? 'error' : '';
            const duration = formatDuration(span.duration_ms);

            // Indent based on parent relationship
            const indent = span.parent_span_id ? '  ' : '';

            return `
                <div class="span-row" onclick="toggleSpanDetails(this)">
                    <div class="span-label" title="${escapeHtml(span.name)}">${indent}${escapeHtml(span.name)}</div>
                    <div class="span-bar-container">
                        <div class="span-bar ${statusClass}" style="left: ${left}%; width: ${width}%;"></div>
                    </div>
                    <div class="span-duration">${duration}</div>
                    <div class="span-details">
                        ${renderAttributes(span.attributes)}
                    </div>
                </div>
            `;
        }

        function renderAttributes(attrs) {
            if (!attrs || Object.keys(attrs).length === 0) {
                return '<span style="color: #666;">No attributes</span>';
            }

            const rows = Object.entries(attrs)
                .map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`)
                .join('');

            return `<table class="attr-table">${rows}</table>`;
        }

        function formatDuration(ms) {
            if (ms == null) return '-';
            if (ms < 1) return '<1ms';
            if (ms < 1000) return Math.round(ms) + 'ms';
            return (ms / 1000).toFixed(2) + 's';
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        function toggleTrace(traceId) {
            const el = document.getElementById('trace-' + traceId);
            el.classList.toggle('expanded');
        }

        function toggleSpanDetails(row) {
            row.classList.toggle('selected');
            event.stopPropagation();
        }

        async function clearTraces() {
            try {
                await fetch('/api/clear', { method: 'POST' });
                traces = [];
                render();
            } catch (err) {
                console.error('Failed to clear:', err);
            }
        }

        function refresh() {
            fetchTraces();
        }

        // Start polling
        fetchTraces();
        refreshInterval = setInterval(fetchTraces, 2000);
    </script>
</body>
</html>
"""
