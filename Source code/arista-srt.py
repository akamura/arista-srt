#**************************************************************************
#   App:         Arista SRT                                               *
#   Version:     0.1                                                      *
#   Author:      Matia Zanella                                            *
#   Description: Arista SRT (Switch Report Tool) is an essential tool     *
#                designed for Network Administrators managing Arista      *
#                switches, allowing to obtain quick switch information in *
#                a styled HTML format.                                    *
#   Github:      https://github.com/akamura/arista-srt                    *
#                                                                         *
#                                                                         *
#   Copyright (C) 2024 Matia Zanella                                      *
#   https://www.matiazanella.com                                          *
#                                                                         *
#   This program is free software; you can redistribute it and/or modify  *
#   it under the terms of the GNU General Public License as published by  *
#   the Free Software Foundation; either version 2 of the License, or     *
#   (at your option) any later version.                                   *
#                                                                         *
#   This program is distributed in the hope that it will be useful,       *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#   GNU General Public License for more details.                          *
#                                                                         *
#   You should have received a copy of the GNU General Public License     *
#   along with this program; if not, write to the                         *
#   Free Software Foundation, Inc.,                                       *
#   59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.             *
#**************************************************************************


# =========================================================================
# IMPORT libraries and modules
# =========================================================================
import json
import requests
from datetime import datetime
import re
import os
import sys


# =========================================================================
# LOGIN configuration
# =========================================================================
SWITCH_URL = "https://YOUR-SWITCH-IP/command-api"
USERNAME = "ADD-YOUR-USERNAME"
PASSWORD = "ADD-YOUR-PASSWORD"


# =========================================================================
# JSON executions
# =========================================================================
def execute_command(commands):
    headers = {'Content-Type': 'application/json'}
    payload = {
        "jsonrpc": "2.0",
        "method": "runCmds",
        "params": {
            "version": 1,
            "cmds": commands,
            "format": "json"
        },
        "id": 1
    }
    try:
        response = requests.post(
            SWITCH_URL,
            headers=headers,
            data=json.dumps(payload),
            auth=(USERNAME, PASSWORD),
            timeout=20
        )
        response.raise_for_status()
        result = response.json()
        if 'error' in result:
            raise Exception(f"API error: {result['error']}")
        return result
    except requests.Timeout:
        raise Exception("Connection timed out while trying to reach the switch.")
    except requests.RequestException as e:
        raise Exception(f"Network error: {e}")
    except json.JSONDecodeError:
        raise Exception("Invalid JSON response from the switch.")


# =========================================================================
# TIME format
# =========================================================================
def format_uptime(seconds):
    weeks = seconds // (7 * 24 * 60 * 60)
    days = (seconds % (7 * 24 * 60 * 60)) // (24 * 60 * 60)
    hours = (seconds % (24 * 60 * 60)) // 3600
    minutes = (seconds % 3600) // 60
    return f"{weeks} weeks, {days} days, {hours} hours and {minutes} minutes"


# =========================================================================
# GET switch informations
# =========================================================================
def get_switch_info():
    commands = ["show version", "show hostname"]
    response = execute_command(commands)

    version_info = response['result'][0]
    hostname_info = response['result'][1]

    bootup_timestamp = version_info.get("bootupTimestamp", 0)
    current_timestamp = datetime.now().timestamp()
    uptime_seconds = int(current_timestamp - bootup_timestamp)

    return {
        "FQDN": hostname_info.get("fqdn", "N/A"),
        "Model": version_info.get("modelName", "N/A"),
        "Serial": version_info.get("serialNumber", "N/A"),
        "MAC Address": version_info.get("systemMacAddress", "N/A"),
        "Image Version": version_info.get("version", "N/A"),
        "Architecture": version_info.get("architecture", "N/A"),
        "Uptime": format_uptime(uptime_seconds),
        "Total Memory (MB)": f"{version_info.get('memTotal', 0) / 1024:.2f}",
        "Free Memory (MB)": f"{version_info.get('memFree', 0) / 1024:.2f}",
    }


# =========================================================================
# GET interface counters
# =========================================================================
def get_interface_counters():
    response_rates = execute_command(["show interfaces counters rates"])
    response_errors = execute_command(["show interfaces counters errors"])

    interfaces_rates = response_rates['result'][0]['interfaces']
    interfaces_errors = response_errors['result'][0]['interfaceErrorCounters']

    combined_data = {}
    for port, rate_data in interfaces_rates.items():
        modified_port = port.replace("Ethernet", "Eth")
        error_data = interfaces_errors.get(port, {})
        total_errors = sum([
            error_data.get("inErrors", 0),
            error_data.get("outErrors", 0),
            error_data.get("frameTooLongs", 0),
            error_data.get("frameTooShorts", 0),
            error_data.get("fcsErrors", 0),
            error_data.get("alignmentErrors", 0),
            error_data.get("symbolErrors", 0)
        ])
        combined_data[modified_port] = {
            "description": rate_data.get("description", ""),
            "outBpsRate": rate_data.get("outBpsRate", 0),
            "inBpsRate": rate_data.get("inBpsRate", 0),
            "totalErrors": total_errors,
            "inErrors": error_data.get("inErrors", 0),
            "outErrors": error_data.get("outErrors", 0),
            "frameTooLongs": error_data.get("frameTooLongs", 0),
            "frameTooShorts": error_data.get("frameTooShorts", 0),
            "fcsErrors": error_data.get("fcsErrors", 0),
            "alignmentErrors": error_data.get("alignmentErrors", 0),
            "symbolErrors": error_data.get("symbolErrors", 0),
        }

    return combined_data


# =========================================================================
# GET environment informations
# =========================================================================
def get_environment_info():
    commands = ["show environment all"]
    response = execute_command(commands)
    env_info = response['result'][0]

    messages = env_info.get("messages", [])
    if not messages:
        return {
            "Cooling Status": "N/A",
            "Ambient Temperature": "N/A",
            "Fan Status": ["N/A"],
            "Power Supply Status": ["N/A"]
        }

    message_str = messages[0]

    # Split the result into lines
    lines = message_str.splitlines()

    # Initialize variables
    cooling_status = "N/A"
    ambient_temperature = "N/A"
    airflow = "N/A"
    fan_status_list = []
    power_supply_status_list = []

    # Flags to indicate which table we're parsing
    parsing_fan = False
    parsing_power = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # GET Cooling Status
        cooling_match = re.match(r"System cooling status is:\s*(\w+)", line)
        if cooling_match:
            cooling_status = cooling_match.group(1)
            continue

        # GET Ambient Temperature
        temp_match = re.match(r"Ambient temperature:\s*(\d+)C", line)
        if temp_match:
            ambient_temperature = f"{temp_match.group(1)}C"
            continue

        # GET Airflow
        airflow_match = re.match(r"Airflow:\s*(.+)", line)
        if airflow_match:
            airflow = airflow_match.group(1)
            continue

        # Detect the start of the Fan Status table
        if line.startswith("Fan") and "Status" in line:
            parsing_fan = True
            parsing_power = False
            continue

        # Detect the start of the Power Supply Status table
        if line.startswith("Power") and "Supply" in line:
            parsing_power = True
            parsing_fan = False
            continue

        # Skip table headers
        if re.match(r"[-\s]+", line):
            continue

        # Parse Fan Status entries
        if parsing_fan:
            fan_match = re.match(r"(\S+)\s+(\w+)\s+(\d+)%\s+(\d+)%", line)
            if fan_match:
                fan_label = fan_match.group(1).replace("Ethernet", "Eth")
                status = fan_match.group(2)
                configured_speed = fan_match.group(3)
                actual_speed = fan_match.group(4)
                fan_status_list.append(
                    f"<strong>{fan_label} Status:</strong> {status}, <strong>Configured Speed:</strong> {configured_speed}%, <strong>Actual Speed:</strong> {actual_speed}%"
                )
            continue

        # Parse Power Supply Status entries
        if parsing_power:
            power_match = re.match(r"(\S+)\s+([\w-]+)\s+(\d+W)\s+([\d\.]+A)\s+([\d\.]+A)\s+([\d\.]+W)\s+(\w+)", line)
            if power_match:
                supply_label = power_match.group(1).replace("Ethernet", "Eth")
                model = power_match.group(2)
                capacity = power_match.group(3)
                input_current = power_match.group(4)
                output_current = power_match.group(5)
                power = power_match.group(6)
                status = power_match.group(7)
                power_supply_status_list.append(
                    f"<strong>{supply_label} Status:</strong> {status}, <strong>Model:</strong> {model}, <strong>Capacity:</strong> {capacity}, <strong>Input Current:</strong> {input_current}, <strong>Output Current:</strong> {output_current}, <strong>Power:</strong> {power}"
                )
            continue

    # If no fan or power supply data was parsed, set to N/A
    if not fan_status_list:
        fan_status_list = ["N/A"]
    if not power_supply_status_list:
        power_supply_status_list = ["N/A"]

    environment_info = {
        "Cooling Status": cooling_status,
        "Ambient Temperature": ambient_temperature,
        "Fan Status": fan_status_list,
        "Power Supply Status": power_supply_status_list
    }

    return environment_info


# =========================================================================
# SORT ethernet interfaces
# =========================================================================
def sort_eth_interfaces(interfaces):
    eth_interfaces = {
        port: data for port, data in interfaces.items() if port.startswith("Eth")
    }

    def interface_sort_key(interface_name):
        parts = re.findall(r'\d+', interface_name)
        return [int(part) for part in parts]

    return sorted(
        eth_interfaces.items(),
        key=lambda x: interface_sort_key(x[0])
    )


# =========================================================================
# ARRANGE data for interface statistics and charts
# =========================================================================
def prepare_interface_data(sorted_interfaces):
    labels = [port for port, _ in sorted_interfaces]
    port_numbers = [int(re.findall(r'\d+', port)[0]) for port in labels]

    in_bps_data = [
        data['inBpsRate'] / 1_000_000 if data['inBpsRate'] else 0
        for _, data in sorted_interfaces
    ]
    out_bps_data = [
        data['outBpsRate'] / 1_000_000 if data['outBpsRate'] else 0
        for _, data in sorted_interfaces
    ]

    # Error data arrays
    in_errors_data = [data.get('inErrors', 0) for _, data in sorted_interfaces]
    out_errors_data = [data.get('outErrors', 0) for _, data in sorted_interfaces]
    frame_too_longs_data = [data.get('frameTooLongs', 0) for _, data in sorted_interfaces]
    frame_too_shorts_data = [data.get('frameTooShorts', 0) for _, data in sorted_interfaces]
    fcs_errors_data = [data.get('fcsErrors', 0) for _, data in sorted_interfaces]
    alignment_errors_data = [data.get('alignmentErrors', 0) for _, data in sorted_interfaces]
    symbol_errors_data = [data.get('symbolErrors', 0) for _, data in sorted_interfaces]

    # Calculate total errors per port
    total_errors_data = [data.get('totalErrors', 0) for _, data in sorted_interfaces]

    # Similarly for other data arrays
    return {
        "labels": labels,
        "port_numbers": port_numbers,
        "in_bps_data": in_bps_data,
        "out_bps_data": out_bps_data,
        "in_errors_data": in_errors_data,
        "out_errors_data": out_errors_data,
        "frame_too_longs_data": frame_too_longs_data,
        "frame_too_shorts_data": frame_too_shorts_data,
        "fcs_errors_data": fcs_errors_data,
        "alignment_errors_data": alignment_errors_data,
        "symbol_errors_data": symbol_errors_data,
        "total_errors_data": total_errors_data,
    }


# =========================================================================
# GENERATE interface rows for statistics table
# =========================================================================
def generate_interface_rows(sorted_interfaces):
    rows = ''
    for index, (port, data) in enumerate(sorted_interfaces):
        row = (
            f"<tr><th scope='row'>{index + 1}</th><td>{port}</td><td>{data['description']}</td>"
            f"<td>{data['outBpsRate'] / 1_000_000:.2f}</td><td>{data['inBpsRate'] / 1_000_000:.2f}</td>"
            f"<td>{data.get('inErrors', 0)}</td><td>{data.get('outErrors', 0)}</td>"
            f"<td>{data.get('frameTooLongs', 0)}</td><td>{data.get('frameTooShorts', 0)}</td>"
            f"<td>{data.get('fcsErrors', 0)}</td><td>{data.get('alignmentErrors', 0)}</td>"
            f"<td>{data.get('symbolErrors', 0)}</td></tr>"
        )
        rows += row
    return rows


# =========================================================================
# GENERATE html report
# ========================================================================= 
def generate_html_report():
    switch_info = get_switch_info()
    interface_counters = get_interface_counters()
    environment_info = get_environment_info()

    sorted_eth_interfaces = sort_eth_interfaces(interface_counters)

    data = prepare_interface_data(sorted_eth_interfaces)
    interface_rows = generate_interface_rows(sorted_eth_interfaces)

    traffic_chart_data = json.dumps([
        {
            "port_number": f"Eth{data['port_numbers'][i]}",
            "InBpsRate": data['in_bps_data'][i],
            "OutBpsRate": data['out_bps_data'][i]
        } for i in range(len(data['labels']))
    ])

    error_chart_data = json.dumps([
        {
            "port_number": f"Eth{data['port_numbers'][i]}",
            "InErrors": data['in_errors_data'][i],
            "OutErrors": data['out_errors_data'][i],
            "FrameTooLongs": data['frame_too_longs_data'][i],
            "FrameTooShorts": data['frame_too_shorts_data'][i],
            "FCSErrors": data['fcs_errors_data'][i],
            "AlignmentErrors": data['alignment_errors_data'][i],
            "SymbolErrors": data['symbol_errors_data'][i]
        } for i in range(len(data['labels']))
    ])

    pie_chart_data = [
        {"port": f"Eth{data['port_numbers'][i]}", "totalErrors": data["total_errors_data"][i]}
        for i, (port, _) in enumerate(sorted_eth_interfaces)
        if data["total_errors_data"][i] > 0  # Exclude ports with 0 errors
    ]
    pie_chart_json = json.dumps(pie_chart_data)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Switch Report - {switch_info['FQDN']}</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <script src="https://cdn.amcharts.com/lib/5/index.js"></script>
        <script src="https://cdn.amcharts.com/lib/5/percent.js"></script>
        <script src="https://cdn.amcharts.com/lib/5/themes/Animated.js"></script>
        <script src="https://cdn.amcharts.com/lib/5/xy.js"></script>

        <link rel="stylesheet" href="assets/css/style.css">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    </head>
    <body>
        <header class="bg-light py-3">
            <div class="container-xxl d-flex justify-content-between align-items-center">
                <img src="assets/img/logo_arista.webp" class="logo-header" alt="Arista Logo">
                <span class="badge text-bg-warning">{switch_info['FQDN']}</span>
            </div>
        </header>

        <div class="container-xxl">
            <div class="row">
                <div class="col-md-4">
                    <h3>Switch Information</h3>
                    <ul class="list-group">
                        {''.join(f"<li class='list-group-item'><strong>{key}:</strong> {value}</li>" for key, value in switch_info.items())}
                    </ul>
                </div>
                <div class="col-md-4">
                    <h3>Environment Status</h3>
                    <ul class="list-group">
                        {''.join(f"<li class='list-group-item'><strong>{key}:</strong> {value}</li>" for key, value in environment_info.items() if key not in ["Fan Status", "Power Supply Status"])}
                        <li class='list-group-item'><strong>Fan Status:</strong></li>
                        {''.join(f"<li class='list-group-item'>{status}</li>" for status in environment_info.get("Fan Status", []))}
                        <li class='list-group-item'><strong>Power Supply Status:</strong></li>
                        {''.join(f"<li class='list-group-item'>{status}</li>" for status in environment_info.get("Power Supply Status", []))}
                    </ul>
                </div>
                <div class="col-md-4">
                    <h3>Port Error Distribution</h3>
                    <div id="errorPieChart" style="width: 100%; height: 400px;"></div>
                </div>
            </div>
            <hr class="v-separator">
            <div class="row">
                <div class="col-6">
                    <h2 class="h4 title mt-4">Traffic Chart</h2>
                    <div id="portTrafficChart" style="width: 100%; height: 300px;"></div>
                </div>
                <div class="col-6">
                    <h2 class="h4 title mt-4">Error Chart</h2>
                    <div id="portErrorChart" style="width: 100%; height: 300px;"></div>
                </div>
            </div>
            <hr class="v-separator">
            <h2 class="h4 title mt-4">Interface Statistics</h2>
            <table class="table table-striped" id="interfaceTable">
                <thead>
                    <tr>
                        <th scope="col">#</th>
                        <th scope="col">Port</th>
                        <th scope="col">Description</th>
                        <th scope="col">Out Bps (Mbps)</th>
                        <th scope="col">In Bps (Mbps)</th>
                        <th scope="col">In Errors</th>
                        <th scope="col">Out Errors</th>
                        <th scope="col">Frame Too Longs</th>
                        <th scope="col">Frame Too Shorts</th>
                        <th scope="col">FCS Errors</th>
                        <th scope="col">Alignment Errors</th>
                        <th scope="col">Symbol Errors</th>
                    </tr>
                </thead>
                <tbody>
                    {interface_rows}
                </tbody>
            </table>
            <p class="footer-report">Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        <footer class="bg-light py-4">
            <div class="container-xxl">
                <div class="row">
                    <!-- Left Column -->
                    <div class="col-md-8 mb-3">
                        <p>&copy; {datetime.now().year} Matia Zanella. All rights reserved.</p>
                        <p>Find the project on <a href="https://github.com/akamura/arista-srt" target="_blank">GitHub</a></p>
                        <p>This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version. You are free and encouraged to contribute on GitHub.</p>
                    </div>
                    <div class="col-md-4 mb-3">
                    <nav class="navbar navbar-expand-lg bg-body-tertiary">
                        <div class="container-fluid">
                            <div class="collapse navbar-collapse" id="navbarNav">
                            <ul class="navbar-nav">
                                <li class="nav-item">
                                <a class="nav-link" href="https://www.arista.com/en/support/customer-support" target="_blank">Arista Support</a>
                                </li>
                                <li class="nav-item">
                                <a class="nav-link" href="https://arista.my.site.com/AristaCommunity/s/knowledge#t=All&sort=relevancy" target="_blank">Knowledge Base</a>
                                </li>
                                <li class="nav-item">
                                <a class="nav-link" href="https://www.arista.com/en/support/software-download" target="_blank">Software Download</a>
                                </li>
                                <li class="nav-item">
                                <a class="nav-link" href="https://www.arista.com/en/support/product-documentation" target="_blank">Product Documentation</a>
                                </li>
                            </ul>
                            </div>
                        </div>
                    </nav>
                    </div>
                </div>
            </div>
        </footer>
        <script>
            am5.ready(function() {{
                var rootTraffic = am5.Root.new("portTrafficChart");
                rootTraffic.setThemes([
                    am5themes_Animated.new(rootTraffic)
                ]);
                var chartTraffic = rootTraffic.container.children.push(
                    am5xy.XYChart.new(rootTraffic, {{
                        panX: true,
                        panY: false,
                        wheelX: "panX",
                        wheelY: "zoomX",
                        pinchZoomX: true,
                        zoomOutButton: am5.Button.new(rootTraffic, {{
                            x: am5.percent(95),
                            y: am5.percent(0),
                            centerX: am5.percent(50),
                            centerY: am5.percent(0),
                            label: am5.Label.new(rootTraffic, {{ text: "Reset Zoom" }})
                        }})
                    }})
                );

                chartTraffic.zoomOutButton.events.on("click", function() {{
                    chartTraffic.goHome();
                }});

                var xRendererTraffic = am5xy.AxisRendererX.new(rootTraffic, {{ minGridDistance: 20 }});
                xRendererTraffic.labels.template.setAll({{
                    rotation: -45,
                    centerY: am5.p50,
                    centerX: am5.p100,
                    oversizedBehavior: "truncate",
                    fontSize: 12
                }});

                var xAxisTraffic = chartTraffic.xAxes.push(
                    am5xy.CategoryAxis.new(rootTraffic, {{
                        maxDeviation: 0,
                        categoryField: "port_number",
                        renderer: xRendererTraffic,
                        tooltip: am5.Tooltip.new(rootTraffic, {{ themeTags: ["axis"] }})
                    }})
                );

                var yAxisTraffic = chartTraffic.yAxes.push(
                    am5xy.ValueAxis.new(rootTraffic, {{
                        renderer: am5xy.AxisRendererY.new(rootTraffic, {{}}),
                        tooltip: am5.Tooltip.new(rootTraffic, {{ themeTags: ["axis"] }})
                    }})
                );

                var dataTraffic = {traffic_chart_data};

                xAxisTraffic.data.setAll(dataTraffic);

                function makeSeriesTraffic(name, fieldName, color) {{
                    var series = chartTraffic.series.push(
                        am5xy.ColumnSeries.new(rootTraffic, {{
                            name: name,
                            xAxis: xAxisTraffic,
                            yAxis: yAxisTraffic,
                            valueYField: fieldName,
                            categoryXField: "port_number",
                            tooltip: am5.Tooltip.new(rootTraffic, {{
                                labelText: "{{{{name}}}} on Port {{{{port_number}}}}: {{{{valueY}}}} Mbps"
                            }}),
                            fill: color,
                            stroke: color
                        }})
                    );

                    series.columns.template.setAll({{
                        width: am5.percent(80)
                    }});

                    series.data.setAll(dataTraffic);

                    series.appear();

                    legendTraffic.data.push(series);
                }}

                var legendTraffic = chartTraffic.children.push(am5.Legend.new(rootTraffic, {{
                    centerX: am5.p50,
                    x: am5.p50
                }}));

                makeSeriesTraffic("In Rate (Mbps)", "InBpsRate", am5.color("#0455BF"));
                makeSeriesTraffic("Out Rate (Mbps)", "OutBpsRate", am5.color("#2E97F2"));

                chartTraffic.appear(1000, 100);

                var rootError = am5.Root.new("portErrorChart");
                rootError.setThemes([
                    am5themes_Animated.new(rootError)
                ]);

                var chartError = rootError.container.children.push(
                    am5xy.XYChart.new(rootError, {{
                        panX: true,
                        panY: false,
                        wheelX: "panX",
                        wheelY: "zoomX",
                        pinchZoomX: true,
                        zoomOutButton: am5.Button.new(rootError, {{
                            x: am5.percent(95),
                            y: am5.percent(0),
                            centerX: am5.percent(50),
                            centerY: am5.percent(0),
                            label: am5.Label.new(rootError, {{ text: "Reset Zoom" }})
                        }})
                    }})
                );

                chartError.zoomOutButton.events.on("click", function() {{
                    chartError.goHome();
                }});

                var xRendererError = am5xy.AxisRendererX.new(rootError, {{ minGridDistance: 20 }});
                xRendererError.labels.template.setAll({{
                    rotation: -45,
                    centerY: am5.p50,
                    centerX: am5.p100,
                    oversizedBehavior: "truncate",
                    fontSize: 12
                }});

                var xAxisError = chartError.xAxes.push(
                    am5xy.CategoryAxis.new(rootError, {{
                        maxDeviation: 0,
                        categoryField: "port_number",
                        renderer: xRendererError,
                        tooltip: am5.Tooltip.new(rootError, {{ themeTags: ["axis"] }})
                    }})
                );

                var yAxisError = chartError.yAxes.push(
                    am5xy.ValueAxis.new(rootError, {{
                        renderer: am5xy.AxisRendererY.new(rootError, {{}}),
                        tooltip: am5.Tooltip.new(rootError, {{ themeTags: ["axis"] }})
                    }})
                );

                var dataError = {error_chart_data};

                xAxisError.data.setAll(dataError);

                function makeSeriesError(name, fieldName, color) {{
                    var series = chartError.series.push(
                        am5xy.ColumnSeries.new(rootError, {{
                            name: name,
                            xAxis: xAxisError,
                            yAxis: yAxisError,
                            valueYField: fieldName,
                            categoryXField: "port_number",
                            tooltip: am5.Tooltip.new(rootError, {{
                                labelText: "{{{{name}}}} on Port {{{{port_number}}}}: {{{{valueY}}}}"
                            }}),
                            fill: color,
                            stroke: color
                        }})
                    );

                    series.columns.template.setAll({{
                        width: am5.percent(80)
                    }});

                    series.data.setAll(dataError);

                    series.appear();

                    legendError.data.push(series);
                }}

                var legendError = chartError.children.push(am5.Legend.new(rootError, {{
                    centerX: am5.p50,
                    x: am5.p50
                }}));

                makeSeriesError("In Errors", "InErrors", am5.color("#E51C1F"));
                makeSeriesError("Out Errors", "OutErrors", am5.color("#F18EA8"));
                makeSeriesError("Frame Too Longs", "FrameTooLongs", am5.color("#F2CC0C"));
                makeSeriesError("Frame Too Shorts", "FrameTooShorts", am5.color("#C626AF"));
                makeSeriesError("FCS Errors", "FCSErrors", am5.color("#FF460E"));
                makeSeriesError("Alignment Errors", "AlignmentErrors", am5.color("#8C533E"));
                makeSeriesError("Symbol Errors", "SymbolErrors", am5.color("#0A1B26"));

                chartError.appear(1000, 100);

                var rootPie = am5.Root.new("errorPieChart");

                rootPie.setThemes([
                    am5themes_Animated.new(rootPie)
                ]);

                var chartPie = rootPie.container.children.push(
                    am5percent.PieChart.new(rootPie, {{
                        layout: rootPie.verticalLayout
                    }})
                );

                var colorSet = am5.ColorSet.new(rootPie, {{
                    colors: [
                        am5.color(0xE51C1F),
                        am5.color(0xF18EA8),
                        am5.color(0xF2CC0C),
                        am5.color(0xC626AF),
                        am5.color(0xFF460E),
                        am5.color(0x8C533E),
                        am5.color(0x0A1B26),
                        am5.color(0x008080),
                        am5.color(0x00BFFF),
                        am5.color(0xDC143C)
                    ]
                }});

                var seriesPie = chartPie.series.push(
                    am5percent.PieSeries.new(rootPie, {{
                        valueField: "totalErrors",
                        categoryField: "port",
                        tooltipText: "{{{{category}}}}: {{{{value}}}} Errors",
                        colors: colorSet  // Apply the color set
                    }})
                );

                seriesPie.data.setAll({pie_chart_json});
                seriesPie.appear(1000, 100);
                chartPie.appear(1000, 100);

            }});
        </script>
    </body>
    </html>
    """
    formatted_datetime = datetime.now().strftime('%Y-%d-%m-%H-%M')
    with open(f"{switch_info['FQDN']}-{formatted_datetime}-report.html", 'w', encoding='utf-8') as f:
        f.write(html_content)


# =========================================================================
# MAIN function
# =========================================================================
def main():
    try:
        generate_html_report()
        print("Report generated successfully")
    except Exception as e:
        print(f"Error generating report: {e}")

if __name__ == "__main__":
    main()