package protocol

import (
	"encoding/json"
	"fmt"
	"testing"

	jsoniter "github.com/json-iterator/go"
	segmentjson "github.com/segmentio/encoding/json"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// BenchmarkCodecComparison measures marshal+unmarshal round-trip cost across
// three JSON codecs (stdlib, json-iterator, segmentio) and three step counts.
func BenchmarkCodecComparison(b *testing.B) {
	type codec struct {
		name      string
		marshal   func(v any) ([]byte, error)
		unmarshal func(data []byte, v any) error
	}

	codecs := []codec{
		{
			name:      "encoding_json",
			marshal:   json.Marshal,
			unmarshal: json.Unmarshal,
		},
		{
			name:      "json_iterator",
			marshal:   jsoniter.ConfigCompatibleWithStandardLibrary.Marshal,
			unmarshal: jsoniter.ConfigCompatibleWithStandardLibrary.Unmarshal,
		},
		{
			name:      "segmentio",
			marshal:   segmentjson.Marshal,
			unmarshal: segmentjson.Unmarshal,
		},
	}

	steps := []int{10, 100, 500}

	for _, c := range codecs {
		for _, n := range steps {
			b.Run(fmt.Sprintf("%s/%d_steps", c.name, n), func(b *testing.B) {
				b.ReportAllocs()

				tr := trace.GenerateSyntheticTraceN(42, n)
				raw, err := c.marshal(tr)
				if err != nil {
					b.Fatal(err)
				}
				b.SetBytes(int64(len(raw)))

				for b.Loop() {
					var out trace.Trace
					if err := c.unmarshal(raw, &out); err != nil {
						b.Fatal(err)
					}
					if _, err := c.marshal(&out); err != nil {
						b.Fatal(err)
					}
				}
			})
		}
	}
}
