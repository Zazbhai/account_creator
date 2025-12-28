# Optimization Notes for 4 vCPU, 16GB RAM Server

## Backend Optimizations Applied

### 1. **Socket.IO Configuration**
- Added `max_http_buffer_size=1e6` (1MB limit) to prevent memory issues
- Set `ping_timeout=60` and `ping_interval=25` for better connection management

### 2. **Parallel Worker Limits**
- **Max parallel workers capped at 8** (2 per CPU core) to prevent resource exhaustion
- This ensures system resources are available for other operations
- Applied in `/api/run` endpoint validation

### 3. **ThreadPoolExecutor Optimization**
- Limited to `min(max_parallel, 8)` workers to prevent CPU contention
- Ensures efficient CPU utilization without overloading

### 4. **Number Queue Worker**
- Increased processing interval from 10s to **15 seconds** to reduce CPU usage
- Reduces background thread overhead

### 5. **Log I/O Optimization**
- **Batched log writes**: Buffer 5 lines before flushing to disk
- **Time-based flushing**: Flush every 0.5 seconds even if buffer not full
- **Increased buffer size**: 8KB file buffering (8192 bytes) for better I/O performance
- Reduces disk I/O operations by ~80%

### 6. **Worker Start Staggering**
- Reduced delay from 2s to **1.5 seconds** between worker starts
- Faster startup while still preventing resource spikes

### 7. **Status Report Wait Time**
- Reduced from 2s to **1.5 seconds** for final status collection
- Faster completion detection

## Frontend Optimizations Applied

### 1. **Polling Intervals**
- **Worker status & margin balance**: Increased from 2s to **3 seconds**
- **Log polling**: Increased from 2s to **3 seconds**
- Reduces API calls by ~33%, lowering CPU and network usage

### 2. **Loading State Management**
- Immediate visual feedback with loading overlay
- Proper state cleanup to prevent memory leaks

## Resource Usage Estimates

### CPU Usage
- **Idle**: ~5-10% (background tasks only)
- **Active (4 workers)**: ~40-60% (1 worker per CPU core)
- **Active (8 workers)**: ~70-85% (2 workers per CPU core)
- **Peak**: ~90% (during worker startup/staggering)

### Memory Usage
- **Base application**: ~200-300 MB
- **Per worker process**: ~150-250 MB
- **4 workers**: ~800 MB - 1.3 GB
- **8 workers**: ~1.4 GB - 2.3 GB
- **Total with overhead**: ~2-3 GB (well within 16GB limit)

### Network Usage
- **Reduced polling**: ~33% fewer API calls
- **Batched logs**: Reduced I/O operations

## Performance Improvements

1. **Reduced CPU Load**: 33% reduction in polling overhead
2. **Reduced I/O**: 80% reduction in disk write operations (batched logs)
3. **Better Resource Management**: Worker limits prevent system overload
4. **Faster Response**: Optimized wait times and staggering
5. **Memory Efficient**: Proper buffering and cleanup

## Recommendations

1. **Monitor CPU usage** - If consistently above 80%, consider reducing max_parallel
2. **Monitor Memory** - With 8 workers, expect ~2-3GB usage
3. **Disk I/O** - Batched logging significantly reduces write operations
4. **Network** - Reduced polling intervals lower bandwidth usage

## Configuration Tuning

If you need to adjust for your specific workload:

- **Increase max_parallel limit**: Edit `MAX_ALLOWED_PARALLEL = 8` in `app_backend.py`
- **Adjust polling intervals**: Edit intervals in `src/pages/Launcher.jsx` (currently 3000ms)
- **Log buffer size**: Edit `buffer_size = 5` in `read_output()` function
- **Log flush interval**: Edit `flush_interval = 0.5` in `read_output()` function


