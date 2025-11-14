import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Set plot style
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

print("Loading CSV file...")
# Read CSV file
df = pd.read_csv('median_timeline_bad_cmp.csv')

print(f"Total records: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

# Display first few rows
print("\nFirst 5 rows of data:")
print(df.head())

# ============================================================================
# Data Preprocessing - Convert microsecond timestamps (hardcoded)
# ============================================================================

# Convert to numeric type
t_raw = pd.to_numeric(df['timestamp'], errors='coerce')

print(f"\nOriginal timestamp range:")
print(f"  Min value: {t_raw.min()}")
print(f"  Max value: {t_raw.max()}")

# ✅ Hardcoded: timestamp is in microseconds, divide by 1e6 to convert to seconds
df['time_seconds'] = (t_raw - t_raw.iloc[0]) / 1e6

total_time = df['time_seconds'].iloc[-1]
print(f"\n✓ Total time: {total_time:.2f} seconds")
print(f"✓ Number of data points: {len(df)}")
if total_time > 0:
    print(f"✓ Sampling rate: {len(df) / total_time:.2f} Hz")

# Process median data
def classify_median(value):
    """Classify median values into categories"""
    try:
        val = float(value)
        if np.isnan(val):
            return 'nan'
        elif 2 <= val <= 4:  # Around 3
            return '3'
        elif 45 <= val <= 55:  # Around 50
            return '50'
        else:
            return 'other'
    except:
        return 'nan'

df['median_class'] = df['data[0]'].apply(classify_median)

# ✅ Process is_blocked data
df['is_blocked'] = pd.to_numeric(df['data[1]'], errors='coerce').fillna(0).astype(int)

# Count statistics for each category
print("\nMedian classification statistics:")
print(df['median_class'].value_counts())

print("\nis_blocked distribution:")
print(df['is_blocked'].value_counts())

# ============================================================================
# ✅ New: Handle NaN values - forward fill with previous valid value
# ============================================================================
def forward_fill_with_marker(df_input):
    """
    Forward fill NaN values and mark which points are filled.
    Returns DataFrame with filled data and markers.
    """
    df_filled = df_input.copy()
    
    # Create a marker column indicating whether the point is an original valid value
    df_filled['is_valid'] = df_filled['median_class'].isin(['50', '3'])
    
    # Forward fill data[0] column
    df_filled['data[0]_filled'] = df_filled['data[0]'].copy()
    
    last_valid = None
    for i in range(len(df_filled)):
        if df_filled['median_class'].iloc[i] in ['50', '3']:
            last_valid = df_filled['data[0]'].iloc[i]
            df_filled.loc[df_filled.index[i], 'data[0]_filled'] = last_valid
        elif df_filled['median_class'].iloc[i] == 'nan' and last_valid is not None:
            df_filled.loc[df_filled.index[i], 'data[0]_filled'] = last_valid
    
    return df_filled

df_processed = forward_fill_with_marker(df)

print(f"\nNumber of data points after filling: {len(df_processed)}")
print(f"Number of valid data points: {df_processed['is_valid'].sum()}")
print(f"Number of filled NaN points: {(~df_processed['is_valid']).sum()}")

# ============================================================================
# Identify time segments
# ============================================================================
def spans_from_mask(t_sec, mask):
    """
    Return continuous time segments as (start, end) tuples.
    For single-point segments, expand slightly using estimated sampling interval.
    """
    spans = []
    in_run = False
    start = None
    
    # Estimate sampling interval for single-point expansion
    if len(t_sec) > 1:
        dt = float(np.nanmedian(np.diff(t_sec)))
    else:
        dt = 0.1
    eps = 0.5 * dt if dt > 0 else 0.05
    
    for i, flag in enumerate(mask):
        if flag and not in_run:
            in_run = True
            start = i
        elif (not flag) and in_run:
            in_run = False
            end = i - 1
            t0 = float(t_sec.iloc[start] - (eps if start == end else 0.0))
            t1 = float(t_sec.iloc[end]   + (eps if start == end else 0.0))
            if t1 < t0: t0, t1 = t1, t0
            spans.append((t0, t1))
    
    # Handle trailing segment
    if in_run:
        end = len(mask) - 1
        t0 = float(t_sec.iloc[start] - (eps if start == end else 0.0))
        t1 = float(t_sec.iloc[end]   + (eps if start == end else 0.0))
        if t1 < t0: t0, t1 = t1, t0
        spans.append((t0, t1))
    
    return spans

# Find all NaN segments (yellow background)
mask_nan = df['median_class'] == 'nan'
nan_segments = spans_from_mask(df['time_seconds'], mask_nan.values)

# Find all segments with value 3 (red background)
mask_3 = df['median_class'] == '3'
three_segments = spans_from_mask(df['time_seconds'], mask_3.values)

# ✅ Find all is_blocked=1 segments
mask_blocked = df['is_blocked'] == 1
blocked_segments = spans_from_mask(df['time_seconds'], mask_blocked.values)

print(f"\nFound {len(nan_segments)} NaN time segments")
print(f"Found {len(three_segments)} value=3 time segments")
print(f"Found {len(blocked_segments)} is_blocked=1 time segments")

# ============================================================================
# ✅ New: Find white gap regions between red and yellow areas
# ============================================================================
def find_gap_segments(three_segs, nan_segs, time_range):
    """
    Find gap regions between the end of red areas and the start of yellow areas.
    These represent transitions that need to be filled.
    """
    gaps = []
    
    # If both red and yellow regions exist
    if len(three_segs) > 0 and len(nan_segs) > 0:
        # Find the end time of the last red region
        red_end = max([end for start, end in three_segs])
        # Find the start time of the first yellow region
        yellow_start = min([start for start, end in nan_segs])
        
        # If there's a gap, add it to the list
        if red_end < yellow_start:
            gaps.append((red_end, yellow_start))
    
    return gaps

gap_segments = find_gap_segments(three_segments, nan_segments, (0, total_time))
print(f"Found {len(gap_segments)} gap regions to fill")

# ============================================================================
# Plotting - Two subplots (upper and lower) with shared x-axis
# ============================================================================
print("\nStarting plot generation...")

# ✅ Create two subplots sharing x-axis
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(5, 2.8), 
                                gridspec_kw={'height_ratios': [1, 0.7]},
                                sharex=True)

# ============================================================================
# Upper plot: Median data
# ============================================================================

# ✅ First, draw gap regions (yellow fill)
for start, end in gap_segments:
    ax1.axvspan(start, end, color='yellow', alpha=1, zorder=1)

# Draw red background for value=3 time segments
for start, end in three_segments:
    ax1.axvspan(start, end, color='red', alpha=1, zorder=1)

# Draw yellow background for NaN time segments
for start, end in nan_segments:
    ax1.axvspan(start, end, color='yellow', alpha=1, zorder=1)

# ============================================================================
# ✅ Corrected plotting logic: Use dashed lines for all transition points
# ============================================================================

segments_solid = []    # Solid line segments (valid data)
segments_dashed = []   # Dashed line segments (filled NaN data or transitions)

current_segment = {'times': [], 'values': [], 'is_valid': None}

for i in range(len(df_processed)):
    row = df_processed.iloc[i]
    
    # Skip points without filled values (initial NaN values)
    if pd.isna(row['data[0]_filled']):
        if current_segment['times']:
            # Save current segment
            if current_segment['is_valid']:
                segments_solid.append(current_segment.copy())
            else:
                segments_dashed.append(current_segment.copy())
            current_segment = {'times': [], 'values': [], 'is_valid': None}
        continue
    
    is_valid = row['is_valid']
    
    # If state changes
    if current_segment['is_valid'] is not None and current_segment['is_valid'] != is_valid:
        # ✅ Key modification: Use dashed lines for all state transitions
        if current_segment['is_valid'] and not is_valid:
            # Transition from valid to filled: save solid segment, create dashed transition
            if len(current_segment['times']) > 0:
                segments_solid.append(current_segment.copy())
            
            last_time = current_segment['times'][-1] if current_segment['times'] else row['time_seconds']
            last_value = current_segment['values'][-1] if current_segment['values'] else row['data[0]_filled']
            
            segments_dashed.append({
                'times': [last_time, row['time_seconds']],
                'values': [last_value, row['data[0]_filled']],
                'is_valid': False
            })
            
            current_segment = {
                'times': [row['time_seconds']], 
                'values': [row['data[0]_filled']], 
                'is_valid': is_valid
            }
        elif not current_segment['is_valid'] and is_valid:
            # ✅ Transition from filled to valid: save dashed segment, create dashed transition to new solid segment
            last_time = current_segment['times'][-1] if current_segment['times'] else row['time_seconds']
            last_value = current_segment['values'][-1] if current_segment['values'] else row['data[0]_filled']
            
            # Add current point to dashed segment
            current_segment['times'].append(row['time_seconds'])
            current_segment['values'].append(row['data[0]_filled'])
            
            if len(current_segment['times']) > 0:
                segments_dashed.append(current_segment.copy())
            
            # Start new segment from current point (solid segment)
            current_segment = {
                'times': [row['time_seconds']], 
                'values': [row['data[0]_filled']], 
                'is_valid': is_valid
            }
    else:
        # Continue current segment
        if current_segment['is_valid'] is None:
            current_segment['is_valid'] = is_valid
        current_segment['times'].append(row['time_seconds'])
        current_segment['values'].append(row['data[0]_filled'])

# Save last segment
if current_segment['times']:
    if current_segment['is_valid']:
        segments_solid.append(current_segment)
    else:
        segments_dashed.append(current_segment)

print(f"\nPlot segment statistics:")
print(f"  Solid segments: {len(segments_solid)}")
print(f"  Dashed segments: {len(segments_dashed)}")

# Draw solid line segments (valid data)
for seg in segments_solid:
    ax1.plot(seg['times'], seg['values'], 
             color='#4A90E2', linewidth=1.5, alpha=0.9, 
             linestyle='-', zorder=3)

# ✅ Draw dashed line segments (filled NaN data) - increased dash spacing
for seg in segments_dashed:
    ax1.plot(seg['times'], seg['values'], 
             color='#4A90E2', linewidth=1.5, alpha=0.9, 
             linestyle=(0, (1, 1)), zorder=3)

# ✅ Add grid lines
ax1.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.3, zorder=0)

# Set axis labels and title for upper plot
ax1.set_ylabel('Median Value', fontsize=11, fontweight='bold')
ax1.set_title('Median Filter Output & Fog Block Behavior', fontsize=12, fontweight='bold', pad=10)

# Set y-axis range
ax1.set_ylim(0, 60)

# ✅ Restore original legend
legend_elements_1 = [
    Patch(facecolor='red', alpha=1.0, label='Med = Outlier'),
    Patch(facecolor='yellow', alpha=1.0, label='Med = NaN'),
    plt.Line2D([0], [0], color='#4A90E2', linewidth=2, label='Returned Median')
]

ax1.legend(handles=legend_elements_1, 
           loc='lower right',
           fontsize=9,
           framealpha=0.9,
           edgecolor='gray',
           fancybox=False,
           frameon=True,
           handlelength=1.0,
           handleheight=0.7,
           handletextpad=0.5,
           borderpad=0.3,
           labelspacing=0.3)

# ============================================================================
# Lower plot: is_blocked status
# ============================================================================

# Draw red background for is_blocked=1 time segments
for start, end in blocked_segments:
    ax2.axvspan(start, end, color='red', alpha=1, zorder=1)

# ✅ Changed to line plot: draw is_blocked data
df_blocked_sorted = df.sort_values('time_seconds')
ax2.plot(df_blocked_sorted['time_seconds'], df_blocked_sorted['is_blocked'], 
         color='green', linewidth=1.5, alpha=0.9, zorder=2, label='is_blocked Status')

# ✅ Add grid lines
ax2.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.3, zorder=0)

# Set axis labels for lower plot
ax2.set_xlabel('Time (seconds)', fontsize=11, fontweight='bold')
ax2.set_ylabel('is_blocked', fontsize=11, fontweight='bold')

# Set y-axis range and ticks
ax2.set_ylim(-0.2, 1.2)
ax2.set_yticks([0, 1])
ax2.set_yticklabels(['0', '1'], fontsize=9)

# Legend for lower plot
legend_elements_2 = [
    Patch(facecolor='red', alpha=0.8, label='Blocked Period'),
    plt.Line2D([0], [0], color='green', linewidth=2, label='is_blocked Status'),
]

ax2.legend(handles=legend_elements_2, 
           loc='upper right',
           fontsize=9,
           framealpha=0.9,
           edgecolor='gray',
           fancybox=False,
           frameon=True,
           handlelength=1.0,
           handleheight=0.7,
           handletextpad=0.5,
           borderpad=0.3,
           labelspacing=0.3)

# ============================================================================
# Set shared x-axis range
# ============================================================================
ax2.set_xlim(0, 6)

# Tight layout for better spacing
plt.tight_layout()

# Save plot as PNG
plt.savefig('median_timeline.png', dpi=300, bbox_inches='tight')
print("✓ Plot saved: median_timeline.png")

# Save plot as PDF (suitable for papers)
plt.savefig('median_timeline.pdf', bbox_inches='tight')
print("✓ PDF saved: median_timeline.pdf")

plt.close()

# ============================================================================
# Statistical Summary
# ============================================================================
print("\n" + "="*60)
print("=== Statistical Summary ===")
print("="*60)

total_points = len(df)
df_50 = df[df['median_class'] == '50']
df_3 = df[df['median_class'] == '3']
count_50 = len(df_50)
count_3 = len(df_3)
count_nan = len(df[df['median_class'] == 'nan'])
count_blocked_0 = len(df[df['is_blocked'] == 0])
count_blocked_1 = len(df[df['is_blocked'] == 1])

summary = f"""
Time range: 0 to {total_time:.2f} seconds
Total data points: {total_points:,}

Median distribution:
  - Median ≈ 50: {count_50:,} ({count_50/total_points*100:.2f}%)
  - Median ≈ 3: {count_3:,} ({count_3/total_points*100:.2f}%)
  - Median = NaN: {count_nan:,} ({count_nan/total_points*100:.2f}%)

is_blocked distribution:
  - Not Blocked (0): {count_blocked_0:,} ({count_blocked_0/total_points*100:.2f}%)
  - Blocked (1): {count_blocked_1:,} ({count_blocked_1/total_points*100:.2f}%)

Number of NaN time segments: {len(nan_segments)}
Number of value=3 time segments: {len(three_segments)}
Number of blocked time segments: {len(blocked_segments)}
Number of gap fills: {len(gap_segments)}

Plot segment statistics:
  - Solid segments: {len(segments_solid)}
  - Dashed segments: {len(segments_dashed)}
"""

if len(nan_segments) > 0:
    summary += "\nNaN segment details:\n"
    for i, (start, end) in enumerate(nan_segments[:10]):
        duration = end - start
        summary += f"  {i+1}. {start:.2f}s - {end:.2f}s (duration: {duration:.2f}s)\n"
    if len(nan_segments) > 10:
        summary += f"  ... and {len(nan_segments)-10} more segments\n"

if len(three_segments) > 0:
    summary += "\nValue=3 segment details:\n"
    for i, (start, end) in enumerate(three_segments[:10]):
        duration = end - start
        summary += f"  {i+1}. {start:.2f}s - {end:.2f}s (duration: {duration:.2f}s)\n"
    if len(three_segments) > 10:
        summary += f"  ... and {len(three_segments)-10} more segments\n"

if len(blocked_segments) > 0:
    summary += "\nBlocked segment details:\n"
    for i, (start, end) in enumerate(blocked_segments[:10]):
        duration = end - start
        summary += f"  {i+1}. {start:.2f}s - {end:.2f}s (duration: {duration:.2f}s)\n"
    if len(blocked_segments) > 10:
        summary += f"  ... and {len(blocked_segments)-10} more segments\n"

if len(gap_segments) > 0:
    summary += "\nGap fill details:\n"
    for i, (start, end) in enumerate(gap_segments):
        duration = end - start
        summary += f"  {i+1}. {start:.2f}s - {end:.2f}s (duration: {duration:.2f}s)\n"

print(summary)

# Save summary to file
with open('median_timeline_summary.txt', 'w', encoding='utf-8') as f:
    f.write(summary)

print("\n✓ Statistical summary saved: median_timeline_summary.txt")
print("="*60)
print("Done!")