import numpy as np

class BreathingPatternAnalyzer:
    def __init__(self, buffer_size=1000, batch_size=100, std_dev_threshold=7.0, rms_threshold=5.0, 
                 flatline_threshold=0.9, normal_rms_min=5.0, partial_blockage_rms_max=4.0):
        """
        initializes the breathing pattern analyzer with specified parameters.

        parameters:
        - buffer_size: the maximum number of co2 data points to store for analysis.
        - batch_size: the number of recent data points to analyze in each detection cycle.
        - std_dev_threshold: the threshold for standard deviation to determine if the breathing pattern is normal or abnormal.
        - rms_threshold: the threshold for root mean square (rms) value to differentiate normal breathing from potential blockage.
        - flatline_threshold: the proportion of data points that can be within a defined range of the baseline to classify as a flatline.
        - normal_rms_min: the minimum rms value that indicates healthy normal breathing; values below this suggest an issue.
        - partial_blockage_rms_max: the maximum rms value that suggests a partial blockage condition; values above this indicate normal breathing.
        """
        
        # store the parameters for use in detection logic
        self.buffer_size = buffer_size
        self.batch_size = batch_size
        # initialize an array to hold co2 data, pre-filled with zeros
        self.co2_data = np.zeros(buffer_size)
        # variable to store the baseline co2 level
        self.baseline_co2 = None
        # variable to store the previous detected state of breathing
        self.previous_state = None  # initially none to detect the first state
        # counter for detecting transitions to normal breathing
        self.normal_transition_counter = 0
        # store thresholds for various calculations
        self.std_dev_threshold = std_dev_threshold
        self.rms_threshold = rms_threshold
        self.flatline_threshold = flatline_threshold
        self.normal_rms_min = normal_rms_min
        self.partial_blockage_rms_max = partial_blockage_rms_max
        # flag to check if the initial state has been set
        self.initial_state_set = False
        # flag to check if normal breathing has occurred previously
        self.had_normal_breathing = False

    def update_data(self, new_co2_batch):
        # ensure that the new batch of co2 data contains at least one point
        if len(new_co2_batch) < 1:
            raise ValueError("batch must contain at least 1 data point.")

        # shift the current co2 data to make space for the new batch
        self.co2_data = np.roll(self.co2_data, -len(new_co2_batch))
        # update the end of the array with the new co2 data
        self.co2_data[-len(new_co2_batch):] = new_co2_batch

    def detect_pattern(self):
        # check if all co2 data points are nan (not a number)
        if np.isnan(self.co2_data).all():
            return "insufficient data"

        # get the most recent batch of co2 data
        recent_data = self.co2_data[-self.batch_size:]
        
        # check if it's the first time calling detect_pattern
        if not self.initial_state_set:
            # set baseline using the recent data to establish initial conditions
            self.baseline_co2 = np.nanmedian(recent_data)
            self.initial_state_set = True
            return self.detect_initial_state(recent_data)

        # define tolerance for baseline co2 level
        tolerance = 2
        lower_bound = self.baseline_co2 - tolerance  # lower bound for flatline check
        upper_bound = self.baseline_co2 + tolerance  # upper bound for flatline check
        
        # calculate the ratio of data points within the flatline bounds
        flatline_ratio = np.mean((recent_data >= lower_bound) & (recent_data <= upper_bound))
        # calculate the standard deviation of the recent data
        std_dev = np.nanstd(recent_data)
        # calculate the root mean square (rms) amplitude from the baseline co2
        rms_amplitude = np.sqrt(np.mean(np.square(recent_data - self.baseline_co2)))

        # if it's the initial state detection
        if not self.initial_state_set:
            self.initial_state_set = True
            # if flatline ratio exceeds the threshold, record as incorrect insertion
            if flatline_ratio > self.flatline_threshold:
                self.previous_state = "incorrect insertion"
                return "incorrect insertion"
            else:
                self.had_normal_breathing = True
                self.baseline_co2 = np.nanmedian(recent_data)  # set baseline for future comparisons
                self.previous_state = "normal breathing"
                return "normal breathing"

        # detect normal breathing if standard deviation and rms amplitude exceed thresholds
        if std_dev > self.std_dev_threshold and rms_amplitude > self.normal_rms_min:
            self.normal_transition_counter += 1  # increment transition counter for normal breathing
            if self.normal_transition_counter >= 3:  # requires three consecutive detections
                self.had_normal_breathing = True
                self.previous_state = "normal breathing"
                return "normal breathing"
        else:
            self.normal_transition_counter = 0  # reset counter if normal conditions are not met

        # flatline detection context
        if flatline_ratio > self.flatline_threshold:
            self.normal_transition_counter = 0  # reset transition counter
            if self.had_normal_breathing:
                self.previous_state = "accidental decannulation"  # classify as accidental decannulation
                return "accidental decannulation"
            else:
                self.previous_state = "incorrect insertion"  # classify as incorrect insertion
                return "incorrect insertion"

        # full blockage detection
        if std_dev < self.std_dev_threshold / 2 and rms_amplitude < self.rms_threshold / 2:
            self.normal_transition_counter = 0  # reset transition counter
            self.previous_state = "full blockage"  # classify as full blockage
            return "full blockage"

       # partial blockage detection with hysteresis
        if std_dev < self.std_dev_threshold and rms_amplitude < self.partial_blockage_rms_max:
            if self.previous_state == "normal breathing":
                # only transition to partial blockage if we've detected a drop over multiple checks
                self.partial_blockage_counter += 1
                if self.partial_blockage_counter >= 3:  # Stabilize condition for partial blockage
                    self.previous_state = "partial blockage"
                    return "partial blockage"
            else:
                self.partial_blockage_counter = 0  # Reset counter if we are not in normal breathing

        # if none of the conditions match, indicate a transitioning state
        if self.previous_state != "normal breathing":
            return "normal breathing"

        # If we reach here, we are likely in a state of change
        self.previous_state = "transitioning"
        return "transitioning"    
    
    def detect_initial_state(self, recent_data):
        # define tolerance for initial state detection
        tolerance = 2
        # calculate baseline co2 for the initial state detection
        self.baseline_co2 = np.nanmedian(recent_data)
        
        lower_bound = self.baseline_co2 - tolerance  # lower bound for flatline check
        upper_bound = self.baseline_co2 + tolerance  # upper bound for flatline check
        
        # calculate flatline ratio based on recent data
        flatline_ratio = np.mean((recent_data >= lower_bound) & (recent_data <= upper_bound))

        # print the flatline ratio for debugging purposes
        print(f"flatline ratio: {flatline_ratio}")

        # if flatline ratio exceeds threshold, classify as incorrect insertion
        if flatline_ratio > self.flatline_threshold:
            self.previous_state = "incorrect insertion"
            return "incorrect insertion"
        else:
            self.had_normal_breathing = True  # record that normal breathing has been observed
            self.previous_state = "normal breathing"  # set the previous state to normal breathing
            return "normal breathing"  # return normal breathing state
