<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * AJAX endpoint: every video-elicitation annotation, for annotation_viewer.php.
 *
 * The data (annotators' names, usernames and transcripts across every company)
 * used to be served to anyone at /craftpilot-api/annotations-dashboard. It is
 * now fetched server-side with the internal token, for site administrators only.
 *
 * @package   local_craftpilot
 * @copyright 2026
 * @license   http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

define('AJAX_SCRIPT', true);

require('../../config.php');

require_login();
require_capability('moodle/site:config', context_system::instance());

header('Content-Type: application/json');
header('Cache-Control: no-store');

try {
    $client = new \local_craftpilot\backend_client();
    echo json_encode($client->get_annotations_dashboard(), JSON_UNESCAPED_UNICODE);
} catch (\Throwable $e) {
    error_log('CraftPilot annotations_dashboard: ' . $e->getMessage());
    http_response_code(502);
    echo json_encode(['error' => 'CraftPilot backend unavailable']);
}
