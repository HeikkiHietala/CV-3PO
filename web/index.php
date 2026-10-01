<?php
$installedStatusFile = '/var/lib/cv3po/status.json';
$developmentStatusFile = __DIR__ . '/../data/status.json';

$statusFile = file_exists($installedStatusFile)
    ? $installedStatusFile
    : $developmentStatusFile;

if (!is_readable($statusFile)) {
    http_response_code(503);
    die('CV-3PO status is not available.');
}

$data = json_decode(file_get_contents($statusFile), true);

if (!is_array($data) || !isset($data['summary'])) {
    http_response_code(503);
    die('CV-3PO status data is invalid.');
}

$s = $data['summary'];

function h($value): string {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function showValue($value, string $unit = ''): string {
    if ($value === null || $value === '') {
        return '—';
    }

    return h($value) . ($unit ? ' ' . h($unit) : '');
}

function showBool($value): string {
    if ($value === null) {
        return '—';
    }

    return $value ? 'Yes' : 'No';
}

function showDoors($value): string {
    if (!is_array($value)) {
        return '—';
    }

    return count($value) ? h(implode(', ', $value)) : 'None';
}

$updatedAt = $data['updatedAt'] ?? null;
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CV-3PO</title>

<style>
body {
    font-family: sans-serif;
    max-width: 760px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.4;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 28px;
}
th, td {
    padding: 6px 8px;
    border-bottom: 1px solid #ccc;
    text-align: left;
}
th {
    width: 60%;
    font-weight: normal;
}
td {
    font-weight: bold;
}
h2 {
    margin-top: 30px;
    margin-bottom: 5px;
}
footer {
    margin-top: 40px;
    font-size: 0.9em;
}
</style>
</head>

<body>

<h1>CV-3PO</h1>
<p>Vehicle status</p>

<h2>Battery</h2>
<table>
<tr><th>State of charge</th><td><?= showValue($s['soc'] ?? null, '%') ?></td></tr>
<tr><th>Range</th><td><?= showValue($s['rangeKm'] ?? null, 'km') ?></td></tr>
<tr><th>Battery capacity</th><td><?= showValue(isset($s['batteryCapacityWh']) ? $s['batteryCapacityWh'] / 1000 : null, 'kWh') ?></td></tr>
<tr><th>Battery residual energy</th><td><?= showValue(isset($s['batteryResidualWh']) ? $s['batteryResidualWh'] / 1000 : null, 'kWh') ?></td></tr>
<tr><th>Battery health capacity</th><td><?= showValue($s['batteryHealthCapacity'] ?? null, '%') ?></td></tr>
<tr><th>Battery health resistance</th><td><?= showValue($s['batteryHealthResistance'] ?? null, '%') ?></td></tr>
</table>

<h2>Vehicle</h2>
<table>
<tr><th>Odometer</th><td><?= showValue($s['odometerKm'] ?? null, 'km') ?></td></tr>
<tr><th>Outside temperature</th><td><?= showValue($s['outsideTemperature'] ?? null, '°C') ?></td></tr>
<tr><th>Speed</th><td><?= showValue($s['speedKmh'] ?? null, 'km/h') ?></td></tr>
<tr><th>Moving</th><td><?= showBool($s['moving'] ?? null) ?></td></tr>
<tr><th>Driving mode</th><td><?= showValue($s['drivingMode'] ?? null) ?></td></tr>
</table>

<h2>Charging</h2>
<table>
<tr><th>Charging status</th><td><?= showValue($s['chargingStatus'] ?? null) ?></td></tr>
<tr><th>Plugged in</th><td><?= showBool($s['plugged'] ?? null) ?></td></tr>
<tr><th>Remaining time</th><td><?= showValue($s['remainingTime'] ?? null) ?></td></tr>
<tr><th>Charging rate</th><td><?= showValue($s['chargingRate'] ?? null) ?></td></tr>
<tr><th>Charging mode</th><td><?= showValue($s['chargingMode'] ?? null) ?></td></tr>
<tr><th>Charging type</th><td><?= showValue($s['chargingType'] ?? null) ?></td></tr>
<tr><th>Next delayed time</th><td><?= showValue($s['nextDelayedTime'] ?? null) ?></td></tr>
</table>

<h2>Doors</h2>
<table>
<tr><th>Doors locked</th><td><?= showBool($s['doorsLocked'] ?? null) ?></td></tr>
<tr><th>Open doors</th><td><?= showDoors($s['openDoors'] ?? null) ?></td></tr>
</table>

<h2>Climate</h2>
<table>
<tr><th>Preconditioning status</th><td><?= showValue($s['preconditioningStatus'] ?? null) ?></td></tr>
</table>

<h2>Data</h2>
<table>
<tr><th>Last update</th><td><?= showValue($updatedAt) ?></td></tr>
</table>

<footer>
CV-3PO reference web interface
</footer>

</body>
</html>
