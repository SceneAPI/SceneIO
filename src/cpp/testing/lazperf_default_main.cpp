bool sceneio_test_lazperf_default_corrector_rejects();
bool sceneio_test_lazperf_wrapped_coordinate_arithmetic();
bool sceneio_test_lazperf_compressor_full_range();

int main() {
    return sceneio_test_lazperf_default_corrector_rejects() &&
                   sceneio_test_lazperf_wrapped_coordinate_arithmetic() &&
                   sceneio_test_lazperf_compressor_full_range()
               ? 0
               : 1;
}
