# DGEMM Baseline Makefile
# Usage: make          (default N=1024)
#        make N=2048   (override matrix size)
#        make run      (build and run)

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra
LDFLAGS ?= -lm
N       ?= 1024

TARGET  = dgemm

.PHONY: all clean run

all: $(TARGET)

$(TARGET): dgemm.c
	$(CC) $(CFLAGS) -DN=$(N) -o $(TARGET) dgemm.c $(LDFLAGS)

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(TARGET)
