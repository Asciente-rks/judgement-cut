import { useCallback, useEffect, useMemo, useState } from "react";
import logo from "./assets/JudgementCut_Logo.png";
import {
  fetchExchangeRate,
  fetchFeaturedDeals,
  fetchMe,
  fetchPlatforms,
  fetchPriceHistory,
  fetchScraperMonitor,
  fetchThumbnail,
  fetchUsers,
  login,
  searchDeals,
  setUserAdmin,
  togglePlatform,
} from "./lib/api";