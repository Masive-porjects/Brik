export interface PaginationParams {
  page: number;
  pageSize: number;
  search?: string;
}

export interface PaginatedResult<T> {
  items: T[];
  totalCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
}
