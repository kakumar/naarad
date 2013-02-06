import neelix.metric
import os
import datetime

from neelix.metric import Metric

class INNOMetric(Metric):
  C_MAX_COMMANDS = 10
  graph_lib = None
  def __init__(self, metric_type, infile, access, outdir, label, ts_start, ts_end, **other_options):
    Metric.__init__(self, metric_type, infile, access, outdir, label, ts_start, ts_end)
    for (key,val) in other_options.iteritems():
      setattr(self, key, val.split())

  def get_csv(self, column):
    return os.path.join(self.outdir, "{0}.{1}.csv".format(self.metric_type, column))

  def get_csv_C(self, command, column):
    return os.path.join(self.outdir, "{0}.{1}.{2}.csv".format(self.metric_type, command, column))

  def parse(self):
    print "Working on innotop metric:", self.infile
    if self.metric_type == "INNOTOP-C":
      return self.parse_innotop_mode_c()
    elif self.metric_type == "INNOTOP-M":
      return self.parse_innotop_mode_m()
    else:
      return self.parse_innotop_mode_b()

  def parse_innotop_mode_c(self):
    with open(self.infile, 'r') as infh:
      headerline = infh.readline()
      columns = headerline.split()[2:]
      #print "columns:",columns
      outfilehandlers = {}
      for line in infh:
        l = line.strip().split(' ', 1)
        if len(l) <= 1:
          continue
        ts = l[0].strip().replace('T', ' ')
        try:
          nameval = l[1].strip().split('\t', 1)
        except IndexError:
          print "Badly formatted line:", line
          print "Expected tab separated values"
          continue
        command = nameval[0]
        if command not in outfilehandlers:
          # Only looking at top N commands
          if len(outfilehandlers) > self.C_MAX_COMMANDS:
            continue
          # TODO(rmaheshw) : Use collections.defaultdict instead to avoid initializing dicts
          outfilehandlers[command] = {}
        words = nameval[1].split('\t')
        #print command, words, ts
        for i in range(len(words)):
          if self.options and columns[i] not in self.options:
            continue
          if columns[i] not in outfilehandlers[command]:
            outfilehandlers[command][columns[i]] = open(self.get_csv_C(command, columns[i]), 'w')
            self.csv_files.append(self.get_csv_C(command, columns[i]))
          ts = neelix.metric.reconcile_timezones(ts, self.timezone, self.graph_timezone)
          outfilehandlers[command][columns[i]].write(ts+',')
          outfilehandlers[command][columns[i]].write(words[i])
          outfilehandlers[command][columns[i]].write('\n')
      for command in outfilehandlers:
        for column in outfilehandlers[command]:
          outfilehandlers[command][column].close()
    return True

  def parse_innotop_mode_b(self):
    """ Generic parsing method for all other modes """
    with open(self.infile, 'r') as infh:
      # Pre processing to figure out different headers
      max_row_quot = 0
      valrow = -1
      thisrowcolumns = {}
      data = {}
      while True:
        line1 = infh.readline()
        words = line1.split()
        # special case for -I (iostat) option
        # skipping all the 'thread' lines
        if words[1] == "thread" and self.metric_type == "INNOTOP-I":
          while True:
            line1 = infh.readline()
            words = line1.split()
            if neelix.metric.is_number(words[1]):
              line1 = infh.readline()
            else:
              break
        if words[1] == "thread" and self.metric_type == "INNOTOP-R":
          break
        # Skip next line
        infh.readline()
        last_ts = words[0].strip().replace('T', ' ')
        if not neelix.metric.is_number(words[1]):
          thisrowcolumns[max_row_quot] = words[1:]
          #print thisrowcolumns[max_row_quot]
          #print "row", max_row_quot, " len:", len(words[1:])
          for column in words[1:]:
            if self.options and column not in self.options:
              continue
            data[column] = []
          if self.metric_type == "INNOTOP-I":
            data["check_pt_age"] = []
          max_row_quot += 1
        else:
          break
      #print "max_row_quot after pre-proc is", max_row_quot
      #infh.seek(0)
      # Real Processing
      for line in infh:
        l = line.strip().split(' ', 1)
        if len(l) <= 1:
          continue
        ts = l[0].strip().replace('T', ' ')
        if not ts == last_ts:
          last_ts = ts
          valrow = -1
        try:
          words = l[1].strip().split('\t')
        except IndexError:
          print "Bad line:", line
          continue
        # special case for -I (iostat) option
        # skipping all the 'thread' lines
        if words[0] == "thread" or (neelix.metric.is_number(words[0]) and "thread" in words[1]):
          continue
        if neelix.metric.is_number(words[0]):
          valrow += 1
          quot = valrow % max_row_quot
          # Special case for -R, skipping all 'thread' value lines
          if quot >= len(thisrowcolumns):
            continue
          columns = thisrowcolumns[quot]
          #print "len columns:", len(columns), " len words:", len(words), "quot", quot
          #print ts, words
          if len(words) > len(columns):
            continue
          for i in range(len(words)):
            if self.options and columns[i] not in self.options:
              continue
            column = columns[i]
            # Converting -- to 0, seen this for buf_pool_hit_rate
            if words[i] == "--":
              words[i] = "0"
            ts = neelix.metric.reconcile_timezones(ts, self.timezone, self.graph_timezone)
            # Calculating check point age
            if self.metric_type == "INNOTOP-I":
              if column == "log_seq_no":
                log_seq_no = int(words[i])
              elif column == "log_flushed_to":
                check_pt_age = log_seq_no -  int(words[i])
                #print check_pt_age, "check_pt_age"
                tup = [ts, str(check_pt_age)]
                data["check_pt_age"].append(tup)
            tup = [ts, words[i]]
            data[column].append(tup)
    # Post Proc, writing the different out files
    for column in data:
      csvfile = self.get_csv(column)
      self.csv_files.append(csvfile)
      with open(csvfile, 'w') as outfh:
        for tup in data[column]:
          outfh.write(','.join(tup))
          outfh.write('\n')
    return True

  def parse_innotop_mode_m(self):
    """ Special parsing method for Innotop "Replication Status" results (innotop --mode M)"""
    with open(self.infile, 'r') as infh:
      # Pre processing to figure out different headers
      max_row_quot = 0
      valrow = -1
      thisrowcolumns = {}
      data = {}
      last_ts = None
      while True:
        # 2012-05-11T00:00:02 master_host slave_sql_running       time_behind_master      slave_catchup_rate      slave_open_temp_tables  relay_log_pos   last_error
        line1 = infh.readline()
        words = line1.split()
        # Skip next line
        infh.readline()
        is_header = True
        for word in words:
          if neelix.metric.is_number(word):
            print "is_not_header", line1
            last_ts = words[0].strip().replace('T', ' ')
            is_header = False
            break # from this loop
        if len(words) > 2 and is_header:
          thisrowcolumns[max_row_quot] = words[2:]
          for column in thisrowcolumns[max_row_quot]:
            data[column] = []
          max_row_quot += 1
        else:
          break
          # from pre-processing. All headers accounted for

      # Real Processing
      if not last_ts:
        print "last_ts not set, looks like there is no data in file", self.infile
        return True
      infh.seek(0)
      is_bad_line = False
      outfilehandlers = {}
      for line in infh:
        #print "real proc", line
        l = line.strip().split(' ', 1)
        # Blank line
        if len(l) <= 1:
          continue
        ts = l[0].strip().replace('T', ' ')
        if ts != last_ts:
          last_ts = ts
          valrow = -1
        nameval = l[1].strip().split('\t', 1)
        try:
          words = nameval[1].split('\t')
        except IndexError:
          print "Bad line:", line
          continue
        valrow += 1
        command = nameval[0]
        if command not in outfilehandlers:
          outfilehandlers[command] = {}
        quot = valrow % max_row_quot
        columns = thisrowcolumns[quot]
        for i in range(len(words)):
          if len(words) > len(columns):
            print "Mismatched number of columns:", line
            print len(words), len(columns)
            break
          if words[i] in columns:
            print "Skipping line:", line
            valrow -= 1
            break
          if self.options and columns[i] not in self.options:
            continue
          if columns[i] not in outfilehandlers[command]:
            outfilehandlers[command][columns[i]] = open(self.get_csv_C(command, columns[i]),  'w')
            self.csv_files.append(self.get_csv_C(command, columns[i]))
          ts = neelix.metric.reconcile_timezones(ts, self.timezone, self.graph_timezone)
          outfilehandlers[command][columns[i]].write(ts+',')
          outfilehandlers[command][columns[i]].write(words[i])
          outfilehandlers[command][columns[i]].write('\n')
      for command in outfilehandlers:
        for column in outfilehandlers[command]:
          outfilehandlers[command][column].close()
    return True
