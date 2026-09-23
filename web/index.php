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

if (!isset($data['summary'])) {
    http_response_code(503);
    die('CV-3PO status data is invalid.');
}

$s = $data['summary'];
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CV-3PO</title>
</head>
<body>
    <h1>CV-3PO</h1>
    <p>State of charge: <strong><?= htmlspecialchars((string)$s['soc']) ?> %</strong></p>
    <p>Range: <strong><?= htmlspecialchars((string)$s['rangeKm']) ?> km</strong></p>
</body>
</html>
