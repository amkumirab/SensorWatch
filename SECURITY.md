# Security Policy

## Supported versions

SensorWatch is currently an early-stage project. Security fixes are applied to the latest code
on the `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability
reporting feature for this repository when available. Include reproduction steps, affected
components, expected impact, and any suggested mitigation.

Please avoid accessing data that does not belong to you, disrupting services, or publishing
details before a fix is available. Acknowledgement and remediation timelines depend on the
severity and reproducibility of the report.

## Deployment guidance

The default configuration is intended for local demonstration. Before exposing SensorWatch to
untrusted networks, disable the demo endpoint, add device authentication and tenant isolation,
use TLS, configure request limits, move persistence to a production database, and establish
monitoring and backup policies.
