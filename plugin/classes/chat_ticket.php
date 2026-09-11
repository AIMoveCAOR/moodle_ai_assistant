<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

namespace local_craftpilot;

defined('MOODLE_INTERNAL') || die();

/**
 * Short-lived signed ticket that binds a browser's chat request to a Moodle user.
 *
 * chat_proxy.php puts one in the redirect it issues. The CraftPilot backend
 * accepts /api/chat from a browser only with a valid ticket, and only for the
 * user_id the ticket names, so nobody can post to /craftpilot-api/chat as
 * another user. Keep the format in sync with core/chat_ticket.py:
 *
 *   v1.<userid>.<expires>.<hex hmac-sha256(secret, "v1|<userid>|<expires>")>
 *
 * @package   local_craftpilot
 */
class chat_ticket {

    /** Seconds a ticket stays valid. The redirect is followed immediately. */
    public const TTL = 120;

    /**
     * Mint a ticket for a user.
     *
     * @param int $userid Moodle user id the chat request must belong to.
     * @param string $secret The internal API token shared with the backend.
     * @param int $ttl Validity in seconds.
     * @param int|null $now Current Unix time (tests only).
     * @return string The ticket.
     */
    public static function issue(int $userid, string $secret, int $ttl = self::TTL, ?int $now = null): string {
        if ($userid <= 0 || $secret === '') {
            throw new \InvalidArgumentException('A chat ticket needs a user id and the internal API token');
        }
        $expires = ($now ?? time()) + $ttl;
        $signature = hash_hmac('sha256', "v1|{$userid}|{$expires}", $secret);
        return "v1.{$userid}.{$expires}.{$signature}";
    }
}
