package main

import (
	"net/http"
	"os"
	"time"
)

func main() {
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get("http://127.0.0.1:9000/minio/health/ready")
	if err != nil {
		os.Exit(1)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		os.Exit(1)
	}
}
