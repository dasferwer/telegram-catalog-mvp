package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	madmin "github.com/minio/madmin-go/v3"
	minio "github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

func initialize() error {
	endpoint, err := url.Parse(os.Getenv("S3_ENDPOINT"))
	if err != nil || endpoint.Host == "" {
		return errors.New("invalid endpoint")
	}
	rootUser, rootSecret := os.Getenv("S3_ROOT_USER"), os.Getenv("S3_ROOT_PASSWORD")
	user, secret := os.Getenv("S3_ACCESS_KEY"), os.Getenv("S3_SECRET_KEY")
	bucket := os.Getenv("S3_BUCKET")
	if rootUser == "" || rootSecret == "" || user == "" || secret == "" || bucket == "" || rootUser == user {
		return errors.New("separate root and application credentials are required")
	}
	transport := &http.Transport{MaxConnsPerHost: 2, ResponseHeaderTimeout: 5 * time.Second}
	defer transport.CloseIdleConnections()
	secure := endpoint.Scheme == "https"
	client, err := minio.New(endpoint.Host, &minio.Options{Creds: credentials.NewStaticV4(rootUser, rootSecret, ""), Secure: secure, Transport: transport})
	if err != nil {
		return err
	}
	admin, err := madmin.New(endpoint.Host, rootUser, rootSecret, secure)
	if err != nil {
		return err
	}
	admin.SetCustomTransport(transport)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	exists, err := client.BucketExists(ctx, bucket)
	if err != nil {
		return err
	}
	if !exists {
		if err = client.MakeBucket(ctx, bucket, minio.MakeBucketOptions{Region: "us-east-1"}); err != nil {
			return err
		}
	}
	if err = client.SetBucketPolicy(ctx, bucket, ""); err != nil {
		return err
	}
	policy, err := json.Marshal(map[string]any{
		"Version": "2012-10-17", "Statement": []any{
			map[string]any{"Effect": "Allow", "Action": []string{"s3:ListBucket"}, "Resource": []string{"arn:aws:s3:::" + bucket}},
			map[string]any{"Effect": "Allow", "Action": []string{"s3:GetObject"}, "Resource": []string{"arn:aws:s3:::" + bucket + "/*"}},
			map[string]any{"Effect": "Allow", "Action": []string{"s3:PutObject"}, "Resource": []string{"arn:aws:s3:::" + bucket + "/products/*"}},
		},
	})
	if err != nil {
		return err
	}
	if err = admin.AddCannedPolicy(ctx, "catalog-products", policy); err != nil {
		return err
	}
	if err = admin.AddUser(ctx, user, secret); err != nil {
		return err
	}
	info, err := admin.GetUserInfo(ctx, user)
	if err != nil {
		return err
	}
	found := false
	var extra []string
	for _, name := range strings.Split(info.PolicyName, ",") {
		if name == "catalog-products" {
			found = true
		} else if name != "" {
			extra = append(extra, name)
		}
	}
	if len(extra) > 0 {
		if _, err = admin.DetachPolicy(ctx, madmin.PolicyAssociationReq{Policies: extra, User: user}); err != nil {
			return err
		}
	}
	if !found {
		_, err = admin.AttachPolicy(ctx, madmin.PolicyAssociationReq{Policies: []string{"catalog-products"}, User: user})
	}
	return err
}

func main() {
	if err := initialize(); err != nil {
		// SDK error strings can contain credentials or signed URLs.
		fmt.Fprintln(os.Stderr, "Storage initialization failed; check configuration and connectivity")
		os.Exit(1)
	}
	fmt.Println("Private bucket and restricted application user are ready")
}
