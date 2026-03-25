/*
 * Naive DGEMM (Double-precision General Matrix Multiply)
 * C = alpha * A * B + beta * C
 *
 * Baseline implementation: triple-nested loop, no optimization.
 * Used as the reference for correctness checking and performance comparison.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

/* Default matrix size */
#ifndef N
#define N 1024
#endif

/* Allocate an N x N matrix of doubles, zeroed */
static double *alloc_matrix(int n) {
    double *m = (double *)calloc((size_t)n * n, sizeof(double));
    if (!m) {
        fprintf(stderr, "Failed to allocate %d x %d matrix\n", n, n);
        exit(1);
    }
    return m;
}

/* Fill matrix with reproducible pseudo-random values in [0, 1) */
static void fill_random(double *m, int n, unsigned int seed) {
    srand(seed);
    for (int i = 0; i < n * n; i++) {
        m[i] = (double)rand() / RAND_MAX;
    }
}

/*
 * Naive DGEMM: C = alpha * A * B + beta * C
 * Row-major layout, A[i][j] = A[i * n + j]
 */
void dgemm_naive(int n, double alpha, const double *A, const double *B,
                 double beta, double *C) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            double sum = 0.0;
            for (int k = 0; k < n; k++) {
                sum += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = alpha * sum + beta * C[i * n + j];
        }
    }
}

/* Get wall-clock time in seconds */
static double get_time(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char *argv[]) {
    int n = N;
    if (argc > 1) {
        n = atoi(argv[1]);
        if (n <= 0) n = N;
    }

    printf("DGEMM naive: N = %d\n", n);

    double *A = alloc_matrix(n);
    double *B = alloc_matrix(n);
    double *C = alloc_matrix(n);

    fill_random(A, n, 42);
    fill_random(B, n, 137);
    memset(C, 0, (size_t)n * n * sizeof(double));

    /* Warm-up (small) */
    if (n <= 512) {
        dgemm_naive(n, 1.0, A, B, 0.0, C);
        memset(C, 0, (size_t)n * n * sizeof(double));
    }

    /* Timed run */
    double t0 = get_time();
    dgemm_naive(n, 1.0, A, B, 0.0, C);
    double t1 = get_time();

    double elapsed = t1 - t0;
    double flops = 2.0 * (double)n * (double)n * (double)n;
    double gflops = flops / elapsed / 1e9;

    printf("Elapsed: %.4f sec\n", elapsed);
    printf("Performance: %.2f GFLOPS\n", gflops);

    /* Checksum for correctness verification */
    double checksum = 0.0;
    for (int i = 0; i < n * n; i++) {
        checksum += C[i];
    }
    printf("Checksum: %.6e\n", checksum);

    free(A);
    free(B);
    free(C);

    return 0;
}
