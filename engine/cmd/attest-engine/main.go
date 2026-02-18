package main

import (
	"fmt"
	"os"

	"github.com/attest-framework/attest-bench/engine/internal/protocol"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "usage: attest-engine <command>\ncommands: serve\n")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "serve":
		if err := protocol.Serve(os.Stdin, os.Stdout); err != nil {
			fmt.Fprintf(os.Stderr, "serve: %v\n", err)
			os.Exit(1)
		}
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\ncommands: serve\n", os.Args[1])
		os.Exit(1)
	}
}
