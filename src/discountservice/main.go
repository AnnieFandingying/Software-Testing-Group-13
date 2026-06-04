package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"time"

	"cloud.google.com/go/profiler"
	"github.com/pkg/errors"
	"github.com/sirupsen/logrus"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/discountservice/genproto"
)

const discountListenPort = "50051"

type healthServer struct{}

func (healthServer) Check(context.Context, *healthpb.HealthCheckRequest) (*healthpb.HealthCheckResponse, error) {
	return &healthpb.HealthCheckResponse{Status: healthpb.HealthCheckResponse_SERVING}, nil
}

func (healthServer) Watch(*healthpb.HealthCheckRequest, healthpb.Health_WatchServer) error {
	return status.Errorf(codes.Unimplemented, "watch not implemented")
}

func main() {
	log := logrus.New()
	log.Level = logrus.DebugLevel
	log.Formatter = &logrus.JSONFormatter{
		FieldMap: logrus.FieldMap{
			logrus.FieldKeyTime:  "timestamp",
			logrus.FieldKeyLevel: "severity",
			logrus.FieldKeyMsg:   "message",
		},
		TimestampFormat: time.RFC3339Nano,
	}
	log.Out = os.Stdout

	if os.Getenv("ENABLE_PROFILER") == "1" {
		go initProfiling(log, "discountservice", "1.0.0")
	}

	telemetryURL := os.Getenv("TELEMETRY_SERVICE_URL")
	reporter := telemetryReporter(noopTelemetryReporter{})
	if telemetryURL != "" {
		reporter = &httpTelemetryReporter{
			client: &http.Client{Timeout: 100 * time.Millisecond},
			url:    telemetryURL,
			log:    log,
		}
	}

	port := discountListenPort
	if os.Getenv("PORT") != "" {
		port = os.Getenv("PORT")
	}

	lis, err := net.Listen("tcp", ":"+port)
	if err != nil {
		log.Fatal(err)
	}

	srv := grpc.NewServer()
	pb.RegisterDiscountServiceServer(srv, &discountServer{log: log, telemetry: reporter})
	healthpb.RegisterHealthServer(srv, healthServer{})
	log.Infof("starting to listen on tcp: %q", lis.Addr().String())
	log.Fatal(srv.Serve(lis))
}

func initProfiling(log *logrus.Logger, service, version string) {
	for i := 1; i <= 3; i++ {
		if err := profiler.Start(profiler.Config{
			Service:        service,
			ServiceVersion: version,
		}); err != nil {
			log.Warnf("failed to start profiler: %+v", err)
		} else {
			log.Info("started Stackdriver profiler")
			return
		}
		time.Sleep(time.Second * 10 * time.Duration(i))
	}
}

func (r *httpTelemetryReporter) ReportAsync(evt telemetryEvent) {
	go func() {
		body, err := json.Marshal(evt)
		if err != nil {
			r.log.WithError(err).Warn("failed to marshal telemetry event")
			return
		}
		req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, r.url, bytes.NewReader(body))
		if err != nil {
			r.log.WithError(err).Warn("failed to create telemetry request")
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := r.client.Do(req)
		if err != nil {
			r.log.WithError(errors.Wrap(err, "failed to deliver telemetry event")).Warn("telemetry delivery failed")
			return
		}
		_ = resp.Body.Close()
		if resp.StatusCode >= http.StatusBadRequest {
			r.log.WithField("status_code", resp.StatusCode).Warn("telemetry endpoint responded with non-success status")
		}
	}()
}
