# Documentation for the PX4 Case Study

## Abstract

This is the documentation for the PX4 defective comparator case study presented in the paper: **InvChecker: Understanding the Invariant Expectation in Sorting Functions**. The vulnerability has been disclosed and reported to the official PX4 GitHub repository. See the issue here: [PX4/PX4-Autopilot#25917](https://github.com/PX4/PX4-Autopilot/issues/25917#issue-3623057276)

---

## Table of Contents

- [First-Time Setup](#first-time-setup)
  - [Install and Run PX4](#install-and-run-px4)
  - [Parameter Configuration](#parameter-configuration)
  - [Install Necessary Packages for Flight Log Analysis](#install-necessary-packages-for-flight-log-analysis)
- [Reproduce the Experiment](#reproduce-the-experiment)
  - [Launch the Flight](#launch-the-flight)
  - [Inject the Distance Readings](#inject-the-distance-readings)
  - [Retrieve the Flight Logs](#retrieve-the-flight-logs)
  - [Inspect the Flight Logs](#inspect-the-flight-logs)
- [Source Code Modifications](#source-code-modifications)
  - [Injecting Sensor Readings](#injecting-sensor-readings)
  - [Range Finder Debug Logging](#range-finder-debug-logging)
  - [Bypass NaN Filtering](#bypass-nan-filtering)
  - [Log the Debug Topic](#log-the-debug-topic)
  - [Configure the Simulation World (Optional)](#configure-the-simulation-world-optional)

---

## First-Time Setup

### Install and Run PX4

Install, compile, and run PX4 following the official guide [here](https://docs.px4.io/main/en/dev_setup/dev_env.html). For this case study, we use the **Typhoon H480** vehicle model.

To run the simulation with visualization, execute the following command in your terminal:

    cd ~/PX4-Autopilot
    make px4_sitl gazebo-classic_typhoon_h480

To run without visualization (headless mode, recommended for reducing system load):

    cd ~/PX4-Autopilot
    HEADLESS=1 make px4_sitl gazebo-classic_typhoon_h480

---

### Parameter Configuration

The following commands should be entered in the **PX4 terminal** (the one where you started the SITL simulation).

Configure the flight parameters as follows:

    # Inspect the current value of EKF2_RNG_FOG
    # This parameter represents the maximum visibility threshold of the distance sensor under fog
    param show EKF2_RNG_FOG
    
    # Set the threshold to 10m for demonstration purposes
    param set EKF2_RNG_FOG 10
    
    # Save the parameter to make the change permanent
    param save EKF2_RNG_FOG
    
    # Double-check if the change took effect
    param show EKF2_RNG_FOG

---

### Install Necessary Packages for Flight Log Analysis

To process PX4's special `.ulg` flight log format, which records all critical variables during control loops, you need the `ulog2csv` tool.

Install it using:

    pip3 install pyulog

Verify the installation:

    ulog2csv --help

---

## Reproduce the Experiment

### Launch the Flight

To ensure the `DISTANCE_SENSOR` is working, the drone must be in flight. Command the drone to take off by entering the following in the PX4 terminal:

    commander takeoff

If you're not in headless mode, you will see the drone take off in the Gazebo simulation window.

**Optional:** Change the default takeoff altitude with:

    param set MIS_TAKEOFF_ALT <DESIRED_HEIGHT>  # Height in meters

This is not required to reproduce the experimental results.

---

### Inject the Distance Readings

Keep the terminal running PX4 SITL open. In a **new terminal**, run the sensor-reading injection script:

    python3 inject_distance_sensor.py

You should see in the PX4 terminal that the distance sensor instance has successfully switched to the injected one. 

Wait for approximately **5-30 seconds** (timing heavily depends on the injection pattern; the default configuration should take less than 10 seconds). The script will terminate automatically once the injection is complete.

---

### Retrieve the Flight Logs

The most recent flight log is located at:

    /PX4-Autopilot/build/px4_sitl_default/rootfs/log/<YYYY-MM-DD>/<HH_MM_SS>.ulg

**Important:** It is highly recommended to **copy the log file to a separate directory** for subsequent analysis, as recompilation may clean and rebuild everything in `/PX4-Autopilot/build`, which includes all flight logs.

Example:

    mkdir -p ~/px4_logs
    cp /PX4-Autopilot/build/px4_sitl_default/rootfs/log/<YYYY-MM-DD>/<HH_MM_SS>.ulg ~/px4_logs/

---

### Inspect the Flight Logs

#### Overview

You can upload your flight log to the [official website](https://logs.px4.io/) for a comprehensive analysis. However, for this experiment, we only need to observe two variables—the **calculated median** and the **`_is_blocked` flag**—so local extraction using `ulog2csv` is sufficient.

#### Key Topics to Inspect

1. **`distance_sensor`**: Logs the original input readings from the distance sensor.
2. **`debug_array`**: A debugging log used to record the variables we want to observe (calculated median and blocked-by-fog status).

#### Generate CSV Files

Navigate to the directory where you copied the log file, then run:

    # Replace <HH_MM_SS> with your actual log file name
    ulog2csv <HH_MM_SS>.ulg -m debug_array
    ulog2csv <HH_MM_SS>.ulg -m distance_sensor

You should get **three CSV files**:

- `<HH_MM_SS>_debug_array_0.csv`
- `<HH_MM_SS>_distance_sensor_0.csv`
- `<HH_MM_SS>_distance_sensor_1.csv`

**Note:** It is normal to have two `distance_sensor` log files. The injection script creates a new distance sensor instance. The file with suffix `_1` corresponds to the injected instance, while `_0` corresponds to the intrinsic sensor instance from the simulation.

#### Visualize the Results

Run the provided Python script to visualize the results:

    python3 plot_px4_median.py

#### Understanding the CSV Columns

If you prefer to browse the raw data in the CSV files, here are the critical columns:

**`distance_sensor` topic:**
- `current_distance`: The exact value the distance sensor reads and provides directly to the downstream median filter.

**`debug_array` topic:**
- `data[0]`: Calculated median value.
- `data[1]`: Value for the `_is_blocked` flag.
  - `1.0` = True (the function determines the sensor visibility is seriously blocked by fog)
  - `0.0` = False (sensor is not blocked)

---

## Source Code Modifications

To demonstrate the flaw in the median filter implementation, we temporarily bypass some implicit checks that filter out NaNs. 

**Note:** The purpose of this proof-of-concept experiment is to demonstrate unstable comparator behavior, **not** to provide an exploitation path for adversaries. We have reported this issue to PX4 officials to help make the stack more robust.

All code modifications are marked with the comment `//INV` for easy identification.

---

### Injecting Sensor Readings

For a minimal and modular design, we inject distance sensor readings via MAVLink. However, the native `mavutil.mavlink_connection.mav.distance_sensor_send` function has a range check that prevents the injection of NaN values.

**Modification:** In `mavlink_receiver.cpp` at [line 975](https://github.com/PX4/PX4-Autopilot/blob/82d8813987856c34c5fe8c7ea75ec45e1b57f232/src/modules/mavlink/mavlink_receiver.cpp#L975), replace the existing code with:

    //INV
    if (dist_sensor.current_distance > 60000u && dist_sensor.current_distance < 62000u) {
        ds.current_distance = NAN;
    } else {
        ds.current_distance = static_cast<float>(dist_sensor.current_distance) * 1e-2f;
    }

This allows inputs between 600m and 620m in the injection script to be translated to NaNs before being sent out. Note that `ds.current_distance` natively supports NaN due to its `float` type.

---

### Range Finder Debug Logging

To enable recording of variables in the flight log, add the following code to [sensor_range_finder.cpp](https://github.com/PX4/PX4-Autopilot/blob/82d8813987856c34c5fe8c7ea75ec45e1b57f232/src/modules/ekf2/EKF/aid_sources/range_finder/sensor_range_finder.cpp):

**At the top of the file (includes):**

    //INV
    #include <uORB/Publication.hpp>
    #include <uORB/topics/debug_key_value.h>
    #include <uORB/topics/debug_array.h>
    #include <drivers/drv_hrt.h>         // hrt_absolute_time()
    #include <cstring>                   // std::memset, std::strncpy
    
    // Global uORB publication handle for debug array messages
    static uORB::Publication<debug_array_s> g_dbg_arr{ORB_ID(debug_array)};
    
    /**
     * @brief Publish range finder debug information via uORB debug_array topic
     * 
     * @param median The median range measurement value
     * @param is_blocked Flag indicating whether the range finder is blocked (true) or not (false)
     */
    static inline void rng_debug_publish(const float median, bool is_blocked) {
        debug_array_s m{};
        m.timestamp = hrt_absolute_time();
        m.id = 42;                 // Debug message identifier (choose a unique ID for your module)
        m.data[0] = median;        // Store median range value in first data slot
        m.data[1] = is_blocked ? 1.f : 0.f;   // Store blocked status (1.0 = blocked, 0.0 = not blocked)
        g_dbg_arr.publish(m);
    }

**Inside `SensorRangeFinder::updateFogCheck()` at [line 152](https://github.com/PX4/PX4-Autopilot/blob/82d8813987856c34c5fe8c7ea75ec45e1b57f232/src/modules/ekf2/EKF/aid_sources/range_finder/sensor_range_finder.cpp#L152), add:**

    //INV
    rng_debug_publish(median_dist, _is_blocked);

---

### Bypass NaN Filtering

In `SensorRangeFinder::isDataInRange()` at [line 115](https://github.com/PX4/PX4-Autopilot/blob/82d8813987856c34c5fe8c7ea75ec45e1b57f232/src/modules/ekf2/EKF/aid_sources/range_finder/sensor_range_finder.cpp#L115), modify the function to bypass NaN filtering:

    inline bool SensorRangeFinder::isDataInRange() const
    {
        //INV
        if (!PX4_ISFINITE(_sample.rng)) {
            return true;
        }
        
        return (_sample.rng >= _rng_valid_min_val) && (_sample.rng <= _rng_valid_max_val);
    }

**Justification for the bypass:**
1. The simple in-range check here doesn't appear to be designed with anomalies such as NaNs in mind.
2. This is a loosely-connected stage preceding the median filter; it doesn't seem to be part of the "obeying the ordering invariants" logic.

---

### Log the Debug Topic

To actually write our recorded data into the flight log, add the `debug_array` topic to the default topic list in `logged_topics.cpp` at [line 46](https://github.com/PX4/PX4-Autopilot/blob/82d8813987856c34c5fe8c7ea75ec45e1b57f232/src/modules/logger/logged_topics.cpp#L46):

    //INV
    add_topic("debug_array");

---

### Configure the Simulation World (Optional)

This modification is completely unrelated to the functionality of the experiment but improves aesthetics.

For a cleaner simulation view, you can configure the spawned map in Gazebo at:

    PX4-Autopilot/Tools/simulation/gazebo-classic/sitl_gazebo-classic/worlds/typhoon_h480.world

**Example:** Replace the stone-texture ground with a pure-white plane. Replace the entire contents of `typhoon_h480.world` with:

    <?xml version="1.0" ?>
    <sdf version="1.5">
      <world name="default">
        <gui>
          <plugin name="video_widget" filename="libgazebo_video_stream_widget.so"/>
        </gui>
        <!-- A global light source -->
        <include>
          <uri>model://sun</uri>
        </include>
        <!-- A ground plane -->
        <!-- <include>
          <uri>model://ground_plane</uri>
        </include> -->
        <!-- <include>
          <uri>model://asphalt_plane</uri>
        </include> -->
        <model name='flat_white_floor'>
          <static>true</static>
          <link name='link'>
            <collision name='col'>
              <geometry>
                <plane>
                  <normal>0 0 1</normal>
                  <size>200 200</size>
                </plane>
              </geometry>
            </collision>
            <visual name='vis'>
              <geometry>
                <plane>
                  <normal>0 0 1</normal>
                  <size>200 200</size>
                </plane>
              </geometry>
              <material>
                <ambient>1 1 1 1</ambient>
                <diffuse>1 1 1 1</diffuse>
                <specular>0 0 0 1</specular>
                <emissive>0 0 0 1</emissive>
              </material>
              <cast_shadows>false</cast_shadows>
            </visual>
          </link>
        </model>
    
        <physics name='default_physics' default='0' type='ode'>
          <gravity>0 0 -9.8066</gravity>
          <ode>
            <solver>
              <type>quick</type>
              <iters>50</iters>
              <sor>1.0</sor>
              <use_dynamic_moi_rescaling>0</use_dynamic_moi_rescaling>
            </solver>
            <constraints>
              <cfm>0</cfm>
              <erp>0.2</erp>
              <contact_max_correcting_vel>100</contact_max_correcting_vel>
              <contact_surface_layer>0.001</contact_surface_layer>
            </constraints>
          </ode>
          <max_step_size>0.004</max_step_size>
          <real_time_factor>1</real_time_factor>
          <real_time_update_rate>250</real_time_update_rate>
          <magnetic_field>6.0e-6 2.3e-5 -4.2e-5</magnetic_field>
        </physics>
      </world>
    </sdf>
