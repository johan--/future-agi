import { useEffect, useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import axios, { endpoints } from "src/utils/axios";

const DEFAULT_PAGE_SIZE = 50;
// Cap for the eager variant. Picker payloads for sane projects sit in
// the hundreds; this is the runaway guard if a project's recent sample
// ever produces tens of thousands of realized (idx, key) cells.
const EAGER_MAX_ITEMS = 2000;

/**
 * Picker source for the EvalPicker. Paginated + searchable, wraps the
 * `get_eval_attributes_list` endpoint's `{items, metadata, page_*}`
 * envelope. Use directly for dropdown/autocomplete UX; use
 * `useEvalAttributesEager` when the caller needs the full list (e.g.,
 * to build a filter definition).
 */
export function useEvalAttributesInfinite({
  projectId,
  rowType,
  filters,
  search = "",
  pageSize = DEFAULT_PAGE_SIZE,
  enabled = true,
} = {}) {
  const mergedFilters = useMemo(
    () => ({ project_id: projectId, ...(filters || {}) }),
    [projectId, filters],
  );

  const query = useInfiniteQuery({
    queryKey: [
      "eval-attributes-v2",
      projectId,
      rowType ?? null,
      mergedFilters,
      search,
      pageSize,
    ],
    enabled: Boolean(enabled && projectId),
    initialPageParam: 0,
    queryFn: async ({ pageParam = 0 }) => {
      const response = await axios.get(
        endpoints.project.getEvalAttributeList(),
        {
          params: {
            filters: JSON.stringify(mergedFilters),
            ...(rowType ? { row_type: rowType } : {}),
            page_number: pageParam,
            page_size: pageSize,
            ...(search ? { search } : {}),
          },
        },
      );
      return response.data?.result || {};
    },
    getNextPageParam: (lastPage, allPages) => {
      const total = lastPage?.metadata?.total_rows ?? 0;
      const loaded = allPages.reduce(
        (acc, p) => acc + (p?.items?.length || 0),
        0,
      );
      return loaded < total ? allPages.length : undefined;
    },
  });

  const items = useMemo(
    () => (query.data?.pages || []).flatMap((p) => p?.items || []),
    [query.data],
  );
  const totalRows = query.data?.pages?.[0]?.metadata?.total_rows ?? 0;

  return {
    items,
    totalRows,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isFetchingNextPage: query.isFetchingNextPage,
    hasMore: Boolean(query.hasNextPage),
    fetchMore: query.fetchNextPage,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * Eagerly drain every page of the picker so the caller gets a single
 * flat array. Caps at `EAGER_MAX_ITEMS` so a runaway project can't burn
 * the page through dozens of round-trips. Use this only when the caller
 * genuinely needs the full list (filter-definition generators, dialogs
 * that don't support virtualized scrolling); prefer the infinite hook
 * for dropdowns where the user will rarely scroll past the first page.
 */
export function useEvalAttributesEager({
  projectId,
  rowType,
  filters,
  pageSize = 200,
  enabled = true,
} = {}) {
  const infinite = useEvalAttributesInfinite({
    projectId,
    rowType,
    filters,
    pageSize,
    enabled,
  });

  useEffect(() => {
    if (
      infinite.hasMore &&
      !infinite.isFetchingNextPage &&
      infinite.items.length < EAGER_MAX_ITEMS
    ) {
      infinite.fetchMore();
    }
  }, [
    infinite.hasMore,
    infinite.isFetchingNextPage,
    infinite.items.length,
    infinite.fetchMore,
  ]);

  return {
    items: infinite.items,
    totalRows: infinite.totalRows,
    isLoading: infinite.isLoading || infinite.hasMore,
    error: infinite.error,
    refetch: infinite.refetch,
  };
}
