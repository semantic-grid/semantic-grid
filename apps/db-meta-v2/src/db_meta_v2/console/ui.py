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
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
        }

        header {
            padding: 1rem 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #30363d;
        }

        header h1 {
            font-size: 1rem;
            font-weight: 500;
            color: #58a6ff;
        }

        header .controls {
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        header button {
            background: transparent;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 0.4rem 0.8rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
        }

        header button:hover {
            border-color: #58a6ff;
            color: #58a6ff;
        }

        .status {
            font-size: 0.75rem;
            color: #6e7681;
        }

        .status.connected { color: #3fb950; }
        .status.error { color: #f85149; }

        main {
            padding: 1rem 2rem;
        }

        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: #6e7681;
        }

        .empty-state h2 {
            font-size: 1.25rem;
            margin-bottom: 0.5rem;
            color: #8b949e;
        }

        .trace-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .trace {
            border: 1px solid #30363d;
            border-radius: 6px;
        }

        .trace-header {
            padding: 0.75rem 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }

        .trace-header:hover {
            background: rgba(56, 139, 253, 0.05);
        }

        .trace-title {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .trace-name {
            font-weight: 500;
            color: #58a6ff;
            font-size: 0.9rem;
        }

        .trace-meta {
            font-size: 0.75rem;
            color: #6e7681;
            display: flex;
            gap: 1rem;
        }

        .trace-duration {
            color: #3fb950;
            font-family: monospace;
        }

        .trace-spans {
            padding: 0 1rem 0.75rem;
            display: none;
            border-top: 1px solid #21262d;
        }

        .trace.expanded .trace-spans {
            display: block;
        }

        .timeline {
            padding: 0.5rem 0;
        }

        .span-row {
            padding: 0.4rem 0;
            cursor: pointer;
            border-bottom: 1px solid #21262d;
        }

        .span-row:last-child {
            border-bottom: none;
        }

        .span-row:hover {
            background: rgba(56, 139, 253, 0.03);
        }

        .span-main {
            display: flex;
            align-items: center;
        }

        .span-label {
            width: 180px;
            flex-shrink: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            padding-right: 1rem;
            color: #c9d1d9;
            font-size: 0.8rem;
        }

        .span-label.child {
            padding-left: 1rem;
            color: #8b949e;
        }

        .span-bar-container {
            flex: 1;
            height: 16px;
            position: relative;
            border: 1px solid #30363d;
            border-radius: 2px;
        }

        .span-bar {
            position: absolute;
            height: 100%;
            border-radius: 1px;
            min-width: 2px;
            opacity: 0.8;
        }

        .span-bar.tool {
            background: #58a6ff;
        }

        .span-bar.mcp {
            background: #a371f7;
        }

        .span-bar.internal {
            background: #3fb950;
        }

        .span-bar.error {
            background: #f85149;
        }

        .span-duration {
            width: 70px;
            flex-shrink: 0;
            text-align: right;
            font-family: monospace;
            font-size: 0.75rem;
            color: #6e7681;
            padding-left: 0.5rem;
        }

        .span-details {
            margin-top: 0.5rem;
            padding: 0.5rem;
            border: 1px solid #30363d;
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
            padding: 0.2rem 0.5rem;
            vertical-align: top;
        }

        .attr-table td:first-child {
            color: #8b949e;
            width: 160px;
            white-space: nowrap;
        }

        .attr-table td:last-child {
            color: #7ee787;
            font-family: monospace;
            word-break: break-all;
            white-space: pre-wrap;
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
        <div id="content">
            <div class="empty-state">
                <h2>Loading...</h2>
            </div>
        </div>
    </main>

    <script>
        let traces = [];
        let expandedTraces = new Set();
        let expandedSpans = new Set();

        async function fetchTraces() {
            try {
                const res = await fetch('/api/traces');
                const data = await res.json();
                traces = data.traces || [];
                updateStatus('connected');
                render();
            } catch (err) {
                updateStatus('error');
            }
        }

        function updateStatus(state) {
            const el = document.getElementById('status');
            el.className = 'status ' + state;
            el.textContent = state === 'connected' ? 'Connected' :
                             state === 'error' ? 'Error' : 'Connecting...';
        }

        function render() {
            const content = document.getElementById('content');

            if (traces.length === 0) {
                content.innerHTML = '<div class="empty-state">' +
                    '<h2>No traces yet</h2>' +
                    '<p>Traces appear when the MCP server handles requests.</p></div>';
                return;
            }

            content.innerHTML = '<div class="trace-list">' +
                traces.map(renderTrace).join('') + '</div>';
        }

        function renderTrace(trace) {
            const time = new Date(trace.start_time * 1000).toLocaleTimeString();
            const duration = formatDuration(trace.duration_ms);
            const isExpanded = expandedTraces.has(trace.trace_id);
            const expandedClass = isExpanded ? 'expanded' : '';

            let displayName = trace.root_span || 'Unknown';
            const toolSpan = trace.spans.find(s => s.attributes && s.attributes['tool.name']);
            if (toolSpan) displayName = toolSpan.attributes['tool.name'];

            return '<div class="trace ' + expandedClass + '" id="trace-' + trace.trace_id + '">' +
                '<div class="trace-header" onclick="toggleTrace(\\''+trace.trace_id+'\\')">' +
                    '<div class="trace-title">' +
                        '<span class="trace-name">' + escapeHtml(displayName) + '</span>' +
                    '</div>' +
                    '<div class="trace-meta">' +
                        '<span>' + trace.span_count + ' spans</span>' +
                        '<span class="trace-duration">' + duration + '</span>' +
                        '<span>' + time + '</span>' +
                    '</div>' +
                '</div>' +
                '<div class="trace-spans"><div class="timeline">' +
                    trace.spans.map(function(s) { return renderSpan(s, trace); }).join('') +
                '</div></div></div>';
        }

        function renderSpan(span, trace) {
            const traceStart = trace.start_time;
            const traceDuration = trace.duration_ms || 1;
            const spanStart = span.start_time - traceStart;
            const spanDuration = span.duration_ms || 0;

            const left = Math.max(0, (spanStart * 1000 / traceDuration) * 100);
            const width = Math.max((spanDuration / traceDuration) * 100, 1);

            const isError = span.status === 'error';
            const isChild = !!span.parent_span_id;
            const isTool = span.attributes && span.attributes['tool.name'];
            const isInternal = span.name.includes('db_') || span.name.includes('fetch') ||
                              span.name.includes('validate') || span.name.includes('explain');

            let barClass = 'mcp';
            if (isError) barClass = 'error';
            else if (isTool) barClass = 'tool';
            else if (isInternal) barClass = 'internal';

            const duration = formatDuration(span.duration_ms);
            const spanKey = trace.trace_id + '-' + span.span_id;
            const isSelected = expandedSpans.has(spanKey);
            const selectedClass = isSelected ? 'selected' : '';
            const childClass = isChild ? 'child' : '';

            return '<div class="span-row ' + selectedClass + '" ' +
                'onclick="toggleSpanDetails(\\''+spanKey+'\\', event)">' +
                '<div class="span-main">' +
                    '<div class="span-label ' + childClass + '">' +
                        escapeHtml(span.name) + '</div>' +
                    '<div class="span-bar-container">' +
                        '<div class="span-bar ' + barClass + '" ' +
                            'style="left:'+left+'%;width:'+width+'%"></div>' +
                    '</div>' +
                    '<div class="span-duration">' + duration + '</div>' +
                '</div>' +
                '<div class="span-details">' + renderAttributes(span.attributes) + '</div>' +
            '</div>';
        }

        function renderAttributes(attrs) {
            if (!attrs || Object.keys(attrs).length === 0) {
                return '<span style="color:#6e7681">No attributes</span>';
            }
            let rows = '';
            for (const [k, v] of Object.entries(attrs)) {
                let val = String(v);
                if (val.startsWith('{') || val.startsWith('[')) {
                    try { val = JSON.stringify(JSON.parse(val), null, 2); } catch(e) {}
                }
                rows += '<tr><td>' + escapeHtml(k) + '</td><td>' + escapeHtml(val) + '</td></tr>';
            }
            return '<table class="attr-table">' + rows + '</table>';
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
            if (expandedTraces.has(traceId)) expandedTraces.delete(traceId);
            else expandedTraces.add(traceId);
            render();
        }

        function toggleSpanDetails(spanKey, event) {
            event.stopPropagation();
            if (expandedSpans.has(spanKey)) expandedSpans.delete(spanKey);
            else expandedSpans.add(spanKey);
            render();
        }

        async function clearTraces() {
            await fetch('/api/clear', { method: 'POST' });
            traces = [];
            expandedTraces.clear();
            expandedSpans.clear();
            render();
        }

        function refresh() { fetchTraces(); }

        fetchTraces();
        setInterval(fetchTraces, 2000);
    </script>
</body>
</html>
"""
