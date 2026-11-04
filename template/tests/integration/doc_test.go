//go:build integration

// Package integration holds the tests against real external systems (services, devices,
// network). They build only with the integration tag:
//
//	go test -tags integration ./tests/integration/...
//
// Never skip one for a missing precondition: fail, or keep the test out of this folder.
package integration
